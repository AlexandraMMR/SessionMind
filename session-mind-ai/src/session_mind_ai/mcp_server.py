"""SessionMind AI custom MCP server.

Companion MCP server (distinct from the official `awsevents` and AWS
Knowledge MCP servers) that an agent client (Kiro, Claude Code, Amazon Q
Developer) adds alongside those official servers. It composes them into
the higher-level tools described in the HLDD's "API Surface Mapping":

  - get_user_schedule    -> wraps GetSchedule (REST)
  - get_session_details  -> wraps GetSession (REST)
  - generate_trip_report  -> RAG-style synthesis over notes + session data

`get_speaker_profile` and full `aws_knowledge_search` pass-through are
intentionally NOT re-implemented here: the real AWS Events API does not
expose a dedicated speaker-profile endpoint (session speakers are just
name strings on the session object, see rest-op-getsession.html), and the
AWS Knowledge MCP server is already directly addable by any MCP client, so
duplicating it would add latency without value. `knowledge_client.py` is
used internally by `generate_trip_report`/briefings instead.

Run standalone over stdio:
  python -m session_mind_ai.mcp_server

Configure in an MCP client (e.g. Kiro's .kiro/settings/mcp.json):
  {
    "mcpServers": {
      "session-mind": {
        "command": "python",
        "args": ["-m", "session_mind_ai.mcp_server"],
        "env": { "EVENTS_API_TOKEN": "...", "EVENTS_API_EVENT_ID": "reinvent2026" }
      }
    }
  }
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from .briefing import build_prep_card
from .events_api_client import EventsApiClient
from .notes_store import InMemoryNotesStore, Note
from .social_drafts import build_builder_center_draft, build_linkedin_draft
from .trip_report import build_trip_report_sections, render_markdown

mcp = FastMCP("session-mind-ai")

# Process-lifetime in-memory note store for the stdio server. A deployed
# Lambda-backed variant would inject an OpenSearchNotesStore instead (see
# notes_store.py); kept simple here since MCP stdio servers are per-session
# child processes, not long-lived shared services.
_notes_store = InMemoryNotesStore()


def _client() -> EventsApiClient:
    return EventsApiClient(
        access_token=os.environ.get("EVENTS_API_TOKEN"),
        base_url=os.environ.get("EVENTS_API_BASE_URL", "https://api.awsevents.com"),
    )


def _default_event_id() -> str:
    return os.environ.get("EVENTS_API_EVENT_ID", "reinvent2026")


@mcp.tool()
def get_user_schedule(event_id: str | None = None) -> dict:
    """Fetches the signed-in attendee's schedule (reservations, favorites,
    personal time) via GetSchedule."""
    client = _client()
    try:
        return client.get_schedule(event_id or _default_event_id())
    finally:
        client.close()


@mcp.tool()
def get_session_details(session_id: str, event_id: str | None = None) -> dict:
    """Fetches deep session metadata (abstract, taxonomy, speakers) via GetSession."""
    client = _client()
    try:
        session = client.get_session(event_id or _default_event_id(), session_id)
        return session.__dict__
    finally:
        client.close()


@mcp.tool()
def build_session_prep_card(session_id: str, event_id: str | None = None) -> dict:
    """Builds a 3-bullet pre-session briefing for one session."""
    client = _client()
    try:
        session = client.get_session(event_id or _default_event_id(), session_id)
    finally:
        client.close()
    card = build_prep_card(session)
    return {"session_id": card.session_id, "title": card.title, "bullets": card.bullets, "doc_links": card.doc_links}


@mcp.tool()
def record_session_note(
    session_id: str, text: str, author: str = "attendee", recording_url: str | None = None
) -> str:
    """Stores a note bound to a specific session, for later trip-report synthesis.

    `recording_url` is optional and attendee-supplied (e.g. a YouTube link the
    attendee found themselves) -- the Events API has no recording-URL field
    on a session at all, so this is never auto-discovered or auto-matched.
    """
    _notes_store.add_note(
        Note(session_id=session_id, text=text, author=author, recording_url=recording_url)
    )
    return f"Recorded note for session {session_id}."


def _fetch_trip_report_sections(event_id: str | None):
    """Shared retrieval step behind generate_trip_report and the social
    draft tools: real reserved sessions + the attendee's real notes,
    grouped the same way for all three outputs."""
    client = _client()
    try:
        resolved_event_id = event_id or _default_event_id()
        schedule = client.get_schedule(resolved_event_id)
        session_ids = [r["sessionId"] for r in schedule.get("reservations", []) if r.get("sessionId")]
        sessions = [client.get_session(resolved_event_id, sid) for sid in session_ids]
    finally:
        client.close()

    notes = _notes_store.notes_for_sessions(session_ids)
    return build_trip_report_sections(sessions, notes)


@mcp.tool()
def generate_trip_report(event_id: str | None = None, attendee_name: str = "Attendee") -> str:
    """Aggregates all recorded notes with official session metadata for every
    reserved session and returns a Markdown executive trip report."""
    sections = _fetch_trip_report_sections(event_id)
    return render_markdown(sections, attendee_name=attendee_name)


@mcp.tool()
def generate_linkedin_draft(
    event_id: str | None = None, attendee_name: str = "Attendee", event_name: str = "the event"
) -> str:
    """Drafts a short LinkedIn post from the attendee's real sessions and
    notes. Highlights and hashtags are built only from real catalog/note
    data; closing-thought lines are left as editable placeholders since
    they require the attendee's own voice."""
    sections = _fetch_trip_report_sections(event_id)
    return build_linkedin_draft(sections, attendee_name=attendee_name, event_name=event_name)


@mcp.tool()
def generate_builder_center_draft(
    event_id: str | None = None, attendee_name: str = "Attendee", event_name: str = "the event"
) -> str:
    """Drafts a longer AWS Builder Center blog post from the attendee's
    real sessions and notes, in Markdown. Same real-data retrieval as
    generate_trip_report, reformatted for a blog audience."""
    sections = _fetch_trip_report_sections(event_id)
    return build_builder_center_draft(sections, attendee_name=attendee_name, event_name=event_name)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
