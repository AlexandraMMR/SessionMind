"""CDK stack for SessionMind AI.

Deploys:
  - An SNS topic that pre-session prep cards are published to (push
    notification channel from the HLDD; a mobile/web client subscribes to
    this via SNS -> a downstream delivery mechanism of the attendee's
    choosing).
  - A Lambda worker (`briefing_worker.handler`) triggered every 15 minutes
    by EventBridge, per the HLDD's "Pre-Session Phase".
  - An Amazon OpenSearch Serverless collection + a dedicated data-access
    policy, used by `notes_store.OpenSearchNotesStore` to index attendee
    notes by sessionId, per the HLDD's "Post-Session Phase".
  - A Secrets Manager secret placeholder for the Events API bearer token.

The MCP server (session_mind_ai/mcp_server.py) is intentionally NOT
deployed here -- it runs as a local stdio process under an MCP client,
mirroring how the official AWS Events API and AWS Knowledge MCP servers
are consumed.
"""

from __future__ import annotations

import os
import subprocess

import jsii
from aws_cdk import (
    BundlingOptions,
    Duration,
    ILocalBundling,
    RemovalPolicy,
    Stack,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_opensearchserverless as aoss,
    aws_secretsmanager as secretsmanager,
    aws_sns as sns,
)
from constructs import Construct

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@jsii.implements(ILocalBundling)
class _LocalPipBundling:
    """Tries to bundle the Lambda package with the host's `pip` before
    falling back to Docker-based bundling (SAM build image). This lets
    `cdk synth`/`cdk deploy` work in environments without Docker running
    (e.g. this sandbox), while still being correct in CI/CD environments
    that do have Docker -- CDK calls `try_bundle` first and only invokes
    the Docker `command`/`image` bundling (configured alongside this) if
    it returns False.
    """

    def __init__(self, package_dir_name: str) -> None:
        self._package_dir_name = package_dir_name

    def try_bundle(self, output_dir: str, *, image=None, **kwargs) -> bool:  # noqa: ANN001
        try:
            subprocess.run(
                ["pip", "install", ".", "-t", output_dir],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
            )
            import shutil

            shutil.copytree(
                os.path.join(REPO_ROOT, "src", self._package_dir_name),
                os.path.join(output_dir, self._package_dir_name),
                dirs_exist_ok=True,
            )
            return True
        except Exception:
            return False


class SessionMindStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        token_secret = secretsmanager.Secret(
            self,
            "EventsApiTokenSecret",
            secret_name="session-mind-ai/events-api-token",
            description=(
                "Bearer access token for a Builder-ID-signed-in attendee, used by the briefing "
                "worker Lambda to call the AWS Events API. Populate manually after completing "
                "the OAuth flow."
            ),
        )

        briefing_topic = sns.Topic(
            self,
            "BriefingTopic",
            display_name="SessionMind AI pre-session prep cards",
        )

        collection = aoss.CfnCollection(
            self,
            "NotesCollection",
            name="session-mind-notes",
            type="SEARCH",
            description="Attendee session notes, indexed by sessionId, for trip-report synthesis.",
        )

        encryption_policy = aoss.CfnSecurityPolicy(
            self,
            "NotesEncryptionPolicy",
            name="session-mind-notes-encryption",
            type="encryption",
            policy=(
                '{"Rules":[{"ResourceType":"collection","Resource":'
                '["collection/session-mind-notes"]}],"AWSOwnedKey":true}'
            ),
        )
        collection.add_dependency(encryption_policy)

        network_policy = aoss.CfnSecurityPolicy(
            self,
            "NotesNetworkPolicy",
            name="session-mind-notes-network",
            type="network",
            policy=(
                '[{"Rules":[{"ResourceType":"collection","Resource":'
                '["collection/session-mind-notes"]}],"AllowFromPublic":true}]'
            ),
        )
        collection.add_dependency(network_policy)

        briefing_fn = _lambda.Function(
            self,
            "BriefingWorkerFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="session_mind_ai.briefing_worker.handler",
            code=_lambda.Code.from_asset(
                REPO_ROOT,
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install . -t /asset-output && cp -au src/session_mind_ai /asset-output/",
                    ],
                    local=_LocalPipBundling("session_mind_ai"),
                ),
            ),
            timeout=Duration.seconds(60),
            memory_size=256,
            environment={
                "EVENTS_API_EVENT_ID": "reinvent2026",
                "BRIEFING_SNS_TOPIC_ARN": briefing_topic.topic_arn,
                "EVENTS_API_TOKEN_SECRET_ARN": token_secret.secret_arn,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        token_secret.grant_read(briefing_fn)
        briefing_topic.grant_publish(briefing_fn)

        data_access_policy = aoss.CfnAccessPolicy(
            self,
            "NotesDataAccessPolicy",
            name="session-mind-notes-access",
            type="data",
            policy=(
                '[{"Rules":[{"ResourceType":"collection","Resource":["collection/session-mind-notes"],'
                '"Permission":["aoss:*"]},{"ResourceType":"index","Resource":["index/session-mind-notes/*"],'
                '"Permission":["aoss:*"]}],"Principal":["' + briefing_fn.role.role_arn + '"]}]'
            ),
        )
        data_access_policy.add_dependency(collection)

        # NOTE: the briefing worker's IAM role also needs `aoss:APIAccessAll`
        # scoped to this collection ARN for OpenSearchNotesStore's SigV4
        # requests to succeed; granted broadly here for demo purposes and
        # should be tightened to the specific collection ARN in production.
        briefing_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["aoss:APIAccessAll"],
                resources=[collection.attr_arn],
            )
        )

        events.Rule(
            self,
            "PeriodicBriefingRule",
            schedule=events.Schedule.rate(Duration.minutes(15)),
            targets=[targets.LambdaFunction(briefing_fn)],
        )

        collection.apply_removal_policy(RemovalPolicy.DESTROY)
