"""Attendee notes storage.

Production deployment target is Amazon OpenSearch Serverless (see
infra/session_mind_stack.py), indexed by sessionId as described in the
HLDD's "Post-Session Phase". For unit testing and local demos, this module
also provides an in-memory store implementing the same interface, so
briefing/trip-report logic never has to special-case "no OpenSearch
available".

Real OpenSearch wiring (bulk index / search) is intentionally left as a
thin adapter (`OpenSearchNotesStore`) using `boto3`'s signed HTTP requests,
since OpenSearch Serverless has no dedicated "put note" API of its own --
it's a generic document index reachable via the standard OpenSearch REST
API over SigV4-signed HTTP.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Note:
    session_id: str
    text: str
    author: str
    created_at: float = field(default_factory=time.time)
    # Optional, attendee-supplied recording link (e.g. a YouTube URL the
    # attendee found themselves). Deliberately NOT auto-discovered: the
    # AWS Events API has no recording-URL field on a session at all, and
    # most AWS Summit breakout/lightning talks are never individually
    # posted online, so any automated title-matching against YouTube would
    # risk silently attaching the wrong talk's video to the wrong session
    # -- worse than attaching nothing in a trip report whose value is
    # accuracy. See trip_report.py and docs/hldd.md for the full rationale.
    recording_url: str | None = None


class NotesStore(Protocol):
    def add_note(self, note: Note) -> None: ...

    def notes_for_sessions(self, session_ids: list[str]) -> list[Note]: ...

    def all_notes(self) -> list[Note]: ...


class InMemoryNotesStore:
    """Default store used by tests and local demos."""

    def __init__(self) -> None:
        self._notes: list[Note] = []

    def add_note(self, note: Note) -> None:
        self._notes.append(note)

    def notes_for_sessions(self, session_ids: list[str]) -> list[Note]:
        wanted = set(session_ids)
        return [n for n in self._notes if n.session_id in wanted]

    def all_notes(self) -> list[Note]:
        return list(self._notes)


class OpenSearchNotesStore:
    """Amazon OpenSearch Serverless-backed store.

    Uses SigV4-signed requests via `requests`/`botocore` credential
    signing (no extra service-specific SDK exists for OpenSearch
    Serverless data-plane calls). Kept separate from InMemoryNotesStore so
    application code can depend on the `NotesStore` protocol and swap
    implementations by environment.
    """

    def __init__(self, endpoint: str, index_name: str = "session-notes", region: str = "us-east-1") -> None:
        self._endpoint = endpoint.rstrip("/")
        self._index_name = index_name
        self._region = region

    def _signed_request(self, method: str, path: str, body: dict | None = None):
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        import httpx

        session = boto3.Session()
        credentials = session.get_credentials()
        url = f"{self._endpoint}{path}"
        data = json.dumps(body) if body is not None else None
        request = AWSRequest(method=method, url=url, data=data, headers={"Content-Type": "application/json"})
        SigV4Auth(credentials, "aoss", self._region).add_auth(request)
        prepared_headers = dict(request.headers)
        return httpx.request(method, url, headers=prepared_headers, content=data, timeout=15.0)

    def add_note(self, note: Note) -> None:
        doc = {
            "sessionId": note.session_id,
            "text": note.text,
            "author": note.author,
            "createdAt": note.created_at,
            "recordingUrl": note.recording_url,
        }
        resp = self._signed_request("POST", f"/{self._index_name}/_doc", doc)
        resp.raise_for_status()

    def notes_for_sessions(self, session_ids: list[str]) -> list[Note]:
        query = {"query": {"terms": {"sessionId": session_ids}}, "size": 1000}
        resp = self._signed_request("POST", f"/{self._index_name}/_search", query)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        return [_note_from_hit(h) for h in hits]

    def all_notes(self) -> list[Note]:
        query = {"query": {"match_all": {}}, "size": 1000}
        resp = self._signed_request("POST", f"/{self._index_name}/_search", query)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        return [_note_from_hit(h) for h in hits]


def _note_from_hit(hit: dict) -> Note:
    src = hit["_source"]
    return Note(
        session_id=src["sessionId"],
        text=src["text"],
        author=src.get("author", "unknown"),
        created_at=src.get("createdAt", 0.0),
        recording_url=src.get("recordingUrl"),
    )
