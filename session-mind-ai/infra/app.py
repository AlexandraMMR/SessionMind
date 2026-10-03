#!/usr/bin/env python3
import aws_cdk as cdk

from session_mind_stack import SessionMindStack

app = cdk.App()
SessionMindStack(
    app,
    "SessionMindAiStack",
    description="SessionMind AI - context-aware live briefing & trip-report agent for AWS re:Invent",
)
app.synth()
