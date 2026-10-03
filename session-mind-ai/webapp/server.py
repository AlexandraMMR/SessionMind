"""SessionMind AI -- visual browser demo server.

A thin FastAPI layer over the real `session_mind_ai` package: every
endpoint here calls the exact same `EventsApiClient`, `briefing`,
`trip_report`, and `social_drafts` modules the CLI demo (`scripts/demo.py`)
and the production MCP server (`src/session_mind_ai/mcp_server.py`) use.
Nothing is reimplemented or mocked here -- this is a UI on top of the same
logic, built so the demo is recordable as a browser walkthrough instead of
scrolling terminal output.

Design notes, read before extending:

- No token is used anywhere in this app. It only ever calls `ListEvents`,
  `ListSessions`, and `GetSession` -- all public, no-auth operations on an
  event that does not require registration (see `GET /api/events`, which
  only returns `authenticationRequired: false` events). `GetSchedule` is
  never called, because a public event has no schedule to pull in the
  first place -- the same constraint documented in `scripts/demo.py` and
  `docs/hldd.md`. Instead, the browser demo lets you manually mark real
  sessions as "My Schedule" (`POST /api/sessions/{id}/schedule`), which
  stands in for a real reservation list.
- Per-browser-session state (selected event, cached sessions, your
  schedule, your notes) is kept server-side in memory, keyed by a random
  cookie set on first visit (`_get_demo_session`). This is a deliberate,
  demo-only simplification -- state is lost on server restart and is not
  shared across machines. It exists so two people (or two tabs) viewing
  the demo at once don't stomp on each other's state, which a single
  global variable would do.
- `generate_trip_report`/`generate_linkedin_draft`/`generate_builder_center_draft`
  are template-based and deterministic (see `trip_report.py`/
  `social_drafts.py` docstrings) -- no LLM call happens here, matching the
  rest of the project.

Run with (from the session-mind-ai directory, with the `webapp` extra installed):
  python -m uvicorn webapp.server:app --reload
Then open http://127.0.0.1:8000
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import markdown as markdown_lib
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from session_mind_ai.briefing import build_prep_card
from session_mind_ai.events_api_client import EventsApiClient, EventsApiError, Session
from session_mind_ai.knowledge_client import search_documentation
from session_mind_ai.notes_store import InMemoryNotesStore, Note
from session_mind_ai.social_drafts import build_builder_center_draft, build_linkedin_draft
from session_mind_ai.trip_report import build_trip_report_sections, render_markdown

COOKIE_NAME = "sm_demo_uid"
EVENTS_API_BASE_URL = "https://api.awsevents.com"


@dataclass
class DemoBrowserSession:
    """Everything this one browser/cookie has done in the demo so far."""

    event_id: str | None = None
    event_name: str | None = None
    sessions_by_id: dict[str, Session] = field(default_factory=dict)
    schedule_session_ids: list[str] = field(default_factory=list)
    notes_store: InMemoryNotesStore = field(default_factory=InMemoryNotesStore)
    attendee_name: str = "Attendee"


_browser_sessions: dict[str, DemoBrowserSession] = {}


def _get_demo_session(request: Request, response: Response) -> DemoBrowserSession:
    uid = request.cookies.get(COOKIE_NAME)
    if not uid or uid not in _browser_sessions:
        uid = secrets.token_urlsafe(16)
        _browser_sessions[uid] = DemoBrowserSession()
        response.set_cookie(COOKIE_NAME, uid, httponly=True, samesite="lax")
    return _browser_sessions[uid]


def _events_client() -> EventsApiClient:
    # No access_token: this app only ever touches public, no-registration
    # events, by design (see module docstring).
    return EventsApiClient(base_url=EVENTS_API_BASE_URL)


def _session_to_dict(session: Session) -> dict[str, Any]:
    return {
        "sessionId": session.session_id,
        "title": session.title,
        "abstract": session.abstract,
        "abbreviation": session.abbreviation,
        "type": session.type,
        "level": session.level,
        "room": session.room,
        "start": session.start,
        "end": session.end,
        "topics": session.topics,
        "areasOfInterest": session.areas_of_interest,
        "speakers": session.speakers,
    }


app = FastAPI(title="SessionMind AI Demo")


@app.exception_handler(EventsApiError)
async def events_api_error_handler(_request: Request, exc: EventsApiError) -> JSONResponse:
    # Surfaces the REAL AWS Events API's status code and message rather
    # than masking it behind a generic 500 -- including it is more honest
    # for a demo whose whole point is showing the real API's behavior.
    return JSONResponse(
        status_code=502,
        content={"error": "events_api_error", "upstreamStatus": exc.status_code, "message": str(exc)},
    )


# ---------------------------------------------------------------------------
# Events & sessions (real ListEvents / ListSessions / GetSession)
# ---------------------------------------------------------------------------


@app.get("/api/events")
def list_events() -> list[dict[str, Any]]:
    """Real GET /v1/events, filtered to events that don't require
    registration -- those are the only ones this demo can browse without a
    Builder ID sign-in, since a registration-required event's catalog
    returns 401 with no token."""
    client = _events_client()
    try:
        events = client.list_events()
    finally:
        client.close()
    public_events = [e for e in events if not e.authentication_required]
    return [
        {"eventId": e.event_id, "name": e.name, "startDate": e.start_date, "endDate": e.end_date}
        for e in public_events
    ]


@app.post("/api/events/{event_id}/select")
def select_event(event_id: str, request: Request, response: Response) -> dict[str, Any]:
    """Fetches and caches the real session catalog for one event (real
    ListSessions, paginated internally), and resets this browser's
    schedule/notes -- switching events starts a fresh demo scenario."""
    demo = _get_demo_session(request, response)
    client = _events_client()
    try:
        sessions = client.list_all_sessions(event_id)
    finally:
        client.close()

    demo.event_id = event_id
    demo.sessions_by_id = {s.session_id: s for s in sessions}
    demo.schedule_session_ids = []
    demo.notes_store = InMemoryNotesStore()

    return {"eventId": event_id, "sessionCount": len(sessions)}


@app.get("/api/sessions")
def list_cached_sessions(request: Request, response: Response) -> list[dict[str, Any]]:
    """Returns the currently-selected event's cached session list, sorted
    chronologically (sessions with no known time sort last)."""
    demo = _get_demo_session(request, response)
    sessions = sorted(demo.sessions_by_id.values(), key=lambda s: s.start or "9999")
    return [_session_to_dict(s) for s in sessions]


@app.get("/api/sessions/{session_id}/prep-card")
async def get_prep_card(session_id: str, request: Request, response: Response) -> dict[str, Any]:
    """Real GetSession round trip for the freshest copy of the session,
    plus a real, live query to the official AWS Knowledge MCP server for
    grounding documentation -- the exact same `build_prep_card` the
    production briefing worker and MCP server use."""
    demo = _get_demo_session(request, response)
    if not demo.event_id:
        raise HTTPException(400, "Select an event first.")

    client = _events_client()
    try:
        session = client.get_session(demo.event_id, session_id)
    finally:
        client.close()
    demo.sessions_by_id[session_id] = session

    doc_query = " ".join(session.topics or [session.title])
    try:
        doc_snippets = await search_documentation(doc_query)
    except Exception:
        doc_snippets = []

    card = build_prep_card(session, doc_snippets)
    return {
        "sessionId": card.session_id,
        "title": card.title,
        "bullets": card.bullets,
        "docLinks": card.doc_links,
        "docQuery": doc_query,
    }


# ---------------------------------------------------------------------------
# "My Schedule" -- manual stand-in for GetSchedule (see module docstring)
# ---------------------------------------------------------------------------


@app.post("/api/sessions/{session_id}/schedule")
def add_to_schedule(session_id: str, request: Request, response: Response) -> dict[str, Any]:
    demo = _get_demo_session(request, response)
    if session_id not in demo.sessions_by_id:
        raise HTTPException(404, "Unknown session for the currently-selected event.")
    if session_id not in demo.schedule_session_ids:
        demo.schedule_session_ids.append(session_id)
    return {"scheduleSessionIds": demo.schedule_session_ids}


@app.delete("/api/sessions/{session_id}/schedule")
def remove_from_schedule(session_id: str, request: Request, response: Response) -> dict[str, Any]:
    demo = _get_demo_session(request, response)
    demo.schedule_session_ids = [sid for sid in demo.schedule_session_ids if sid != session_id]
    return {"scheduleSessionIds": demo.schedule_session_ids}


@app.get("/api/schedule")
def get_schedule(request: Request, response: Response) -> list[dict[str, Any]]:
    demo = _get_demo_session(request, response)
    sessions = [demo.sessions_by_id[sid] for sid in demo.schedule_session_ids if sid in demo.sessions_by_id]
    return [_session_to_dict(s) for s in sessions]


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


class NoteIn(BaseModel):
    session_id: str
    text: str
    recording_url: str | None = None


@app.post("/api/notes")
def add_note(note_in: NoteIn, request: Request, response: Response) -> dict[str, Any]:
    demo = _get_demo_session(request, response)
    if note_in.session_id not in demo.sessions_by_id:
        raise HTTPException(404, "Unknown session for the currently-selected event.")
    demo.notes_store.add_note(
        Note(
            session_id=note_in.session_id,
            text=note_in.text,
            author=demo.attendee_name,
            recording_url=note_in.recording_url or None,
        )
    )
    return {"ok": True}


@app.get("/api/notes")
def list_notes(request: Request, response: Response) -> list[dict[str, Any]]:
    demo = _get_demo_session(request, response)
    return [
        {
            "sessionId": n.session_id,
            "text": n.text,
            "createdAt": n.created_at,
            "recordingUrl": n.recording_url,
        }
        for n in demo.notes_store.all_notes()
    ]


# ---------------------------------------------------------------------------
# Reports -- same real data (schedule + notes), three different renderings
# ---------------------------------------------------------------------------


class AttendeeNameIn(BaseModel):
    attendee_name: str = "Attendee"


def _report_sections(demo: DemoBrowserSession):
    sessions = [demo.sessions_by_id[sid] for sid in demo.schedule_session_ids if sid in demo.sessions_by_id]
    notes = demo.notes_store.notes_for_sessions(demo.schedule_session_ids)
    return build_trip_report_sections(sessions, notes)


@app.post("/api/reports/trip-report")
def generate_trip_report_endpoint(body: AttendeeNameIn, request: Request, response: Response) -> dict[str, str]:
    demo = _get_demo_session(request, response)
    demo.attendee_name = body.attendee_name or demo.attendee_name
    sections = _report_sections(demo)
    md = render_markdown(sections, attendee_name=demo.attendee_name)
    return {"markdown": md, "html": markdown_lib.markdown(md)}


@app.post("/api/reports/linkedin")
def generate_linkedin_endpoint(body: AttendeeNameIn, request: Request, response: Response) -> dict[str, str]:
    demo = _get_demo_session(request, response)
    demo.attendee_name = body.attendee_name or demo.attendee_name
    sections = _report_sections(demo)
    md = build_linkedin_draft(sections, attendee_name=demo.attendee_name, event_name=demo.event_id or "the event")
    return {"markdown": md, "html": markdown_lib.markdown(md)}


@app.post("/api/reports/builder-center")
def generate_builder_center_endpoint(body: AttendeeNameIn, request: Request, response: Response) -> dict[str, str]:
    demo = _get_demo_session(request, response)
    demo.attendee_name = body.attendee_name or demo.attendee_name
    sections = _report_sections(demo)
    md = build_builder_center_draft(sections, attendee_name=demo.attendee_name, event_name=demo.event_id or "the event")
    return {"markdown": md, "html": markdown_lib.markdown(md)}


# ---------------------------------------------------------------------------
# Static front end
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "index.html"))
