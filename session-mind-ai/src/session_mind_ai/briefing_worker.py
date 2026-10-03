"""Lambda handler: periodic pre-session briefing worker.

Triggered every 15 minutes by EventBridge (see infra/session_mind_stack.py).
For each reserved session starting within the next 15-20 minutes, builds a
prep card and publishes it to SNS, per the HLDD's "Pre-Session Phase":

  EventBridge (15m) -> Lambda -> GetSchedule -> GetSession (per upcoming)
    -> search_documentation (AWS Knowledge MCP) -> build_prep_card -> SNS

The AWS Knowledge MCP lookup is best-effort: `knowledge_client.search_documentation`
swallows its own errors and returns [], so a knowledge-server outage
degrades briefing quality rather than failing the whole worker run --
matching the ADR-002 "requires fallback error handling for tool call
failures" consequence.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3

from .briefing import build_prep_card
from .events_api_client import EventsApiClient, upcoming_reservations
from .knowledge_client import search_documentation

LOOKAHEAD_MINUTES = int(os.environ.get("BRIEFING_LOOKAHEAD_MINUTES", "15"))
LOOKAHEAD_WINDOW_MINUTES = int(os.environ.get("BRIEFING_WINDOW_MINUTES", "5"))


def _is_upcoming(start_iso: str | None, now: datetime) -> bool:
    if not start_iso:
        return False
    try:
        start = datetime.fromisoformat(start_iso)
    except ValueError:
        return False
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    delta = (start - now).total_seconds() / 60.0
    return LOOKAHEAD_MINUTES <= delta <= LOOKAHEAD_MINUTES + LOOKAHEAD_WINDOW_MINUTES


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    event_id = event.get("eventId", os.environ.get("EVENTS_API_EVENT_ID", "reinvent2026"))
    access_token = event.get("accessToken", os.environ.get("EVENTS_API_TOKEN"))
    sns_topic_arn = os.environ.get("BRIEFING_SNS_TOPIC_ARN")

    client = EventsApiClient(access_token=access_token, base_url=os.environ.get("EVENTS_API_BASE_URL", "https://api.awsevents.com"))
    now = datetime.now(timezone.utc)
    sent = 0
    errors: list[str] = []

    try:
        schedule = client.get_schedule(event_id)
        reservations = [r for r in upcoming_reservations(schedule) if _is_upcoming(r.start_date_time, now)]

        for reservation in reservations:
            if not reservation.session_id:
                continue
            try:
                session = client.get_session(event_id, reservation.session_id)
                doc_snippets = asyncio.run(
                    search_documentation(" ".join(session.topics or [session.title]))
                )
                card = build_prep_card(session, doc_snippets)
                _publish(sns_topic_arn, card)
                sent += 1
            except Exception as exc:  # noqa: BLE001 - one bad session must not stop the batch
                errors.append(f"{reservation.session_id}: {exc}")
    finally:
        client.close()

    result = {"cardsSent": sent, "errors": errors}
    print(json.dumps({"msg": "briefing_worker_complete", **result}))
    return result


def _publish(topic_arn: str | None, card) -> None:
    payload = json.dumps({"session_id": card.session_id, "title": card.title, "bullets": card.bullets})
    if not topic_arn:
        print(json.dumps({"msg": "briefing_card_dry_run", "card": payload}))
        return
    sns = boto3.client("sns")
    sns.publish(TopicArn=topic_arn, Subject=f"Prep card: {card.title}"[:100], Message=payload)
