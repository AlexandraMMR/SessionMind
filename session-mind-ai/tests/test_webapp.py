"""Tests for the FastAPI demo server (webapp/server.py).

No real network calls happen here: `webapp.server._events_client` and
`webapp.server.search_documentation` are monkeypatched to fakes built on
real captured fixture data (the same REAL_SESSION_RAW-style shape used in
test_events_api_client.py), so these tests exercise the actual FastAPI
routing/state-management logic without depending on live traffic or
import ordering. Live-traffic verification is covered separately by
tests/test_live_smoke.py's RUN_LIFE_SMOKE_TESTS-gated tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from session_mind_ai.events_api_client import EventSummary, Session
from webapp import server as server_module

FAKE_SESSION = Session(
    session_id="AIM102-S",
    title="AI That Pays Off (sponsored by CGI Inc.)",
    abstract="Most AI initiatives stall before they show any value.",
    abbreviation="AIM102-S",
    level="100 – Foundational",
    room="Expo, Athena Theater",
    topics=["AI/ML", "Analytics"],
    areas_of_interest=["Cost Optimization", "Generative AI"],
    speakers=["Scott Stanley, CGI Inc."],
    start="2025-09-04T12:30:00",
    end="2025-09-04T13:00:00",
)

FAKE_SESSION_2 = Session(
    session_id="DAT302",
    title="Build a cost-effective RAG-based gen AI application",
    abstract="A deep dive into retrieval-augmented generation on AWS.",
    level="300 – Advanced",
    room="Level 700, Room 709",
    topics=["Databases"],
    areas_of_interest=["Generative AI"],
    start="2025-09-04T08:15:00",
    end="2025-09-04T09:15:00",
)


class FakeEventsApiClient:
    """Stands in for EventsApiClient, built from real fixture-shaped data
    (see REAL_SESSION_RAW in test_events_api_client.py) rather than
    arbitrary made-up values."""

    def __init__(self, sessions=None, events=None):
        self._sessions = sessions if sessions is not None else [FAKE_SESSION, FAKE_SESSION_2]
        self._events = events if events is not None else [
            EventSummary(event_id="Summit-Toronto-2025", name="AWS Summit Toronto 2025", authentication_required=False),
            EventSummary(event_id="reinvent2026", name="re:Invent 2026", authentication_required=True),
        ]
        self.closed = False

    def list_events(self, include_past: bool = False):
        return self._events

    def list_all_sessions(self, event_id: str):
        return self._sessions

    def get_session(self, event_id: str, session_id: str):
        for s in self._sessions:
            if s.session_id == session_id:
                return s
        raise KeyError(session_id)

    def close(self):
        self.closed = True


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server_module, "_events_client", lambda: FakeEventsApiClient())

    async def fake_search_documentation(query, limit=3):
        return [{"title": query, "url": None, "snippet": "A real-looking doc snippet."}]

    monkeypatch.setattr(server_module, "search_documentation", fake_search_documentation)
    # Each test gets isolated server-side state.
    server_module._browser_sessions.clear()
    return TestClient(server_module.app)


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SessionMind AI" in resp.text


def test_list_events_filters_to_public_only(client):
    resp = client.get("/api/events")
    assert resp.status_code == 200
    events = resp.json()
    assert [e["eventId"] for e in events] == ["Summit-Toronto-2025"]


def test_select_event_caches_sessions_and_sets_cookie(client):
    resp = client.post("/api/events/Summit-Toronto-2025/select")
    assert resp.status_code == 200
    assert resp.json() == {"eventId": "Summit-Toronto-2025", "sessionCount": 2}
    assert "sm_demo_uid" in resp.cookies


def test_list_sessions_sorted_chronologically(client):
    client.post("/api/events/Summit-Toronto-2025/select")
    resp = client.get("/api/sessions")
    sessions = resp.json()
    assert [s["sessionId"] for s in sessions] == ["DAT302", "AIM102-S"]


def test_prep_card_returns_bullets_and_doc_query(client):
    client.post("/api/events/Summit-Toronto-2025/select")
    resp = client.get("/api/sessions/AIM102-S/prep-card")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sessionId"] == "AIM102-S"
    assert len(body["bullets"]) == 3
    # build_prep_card's 3rd bullet cites the doc snippet's title (see
    # briefing.py); our fake search_documentation echoes the query back as
    # the title, so assert against that rather than the snippet text.
    assert "Related docs:" in body["bullets"][2]
    assert body["docQuery"] in body["bullets"][2]


def test_prep_card_without_selected_event_returns_400(client):
    resp = client.get("/api/sessions/AIM102-S/prep-card")
    assert resp.status_code == 400


def test_add_and_list_schedule(client):
    client.post("/api/events/Summit-Toronto-2025/select")
    resp = client.post("/api/sessions/AIM102-S/schedule")
    assert resp.status_code == 200
    assert resp.json()["scheduleSessionIds"] == ["AIM102-S"]

    resp = client.get("/api/schedule")
    assert [s["sessionId"] for s in resp.json()] == ["AIM102-S"]


def test_add_unknown_session_to_schedule_returns_404(client):
    client.post("/api/events/Summit-Toronto-2025/select")
    resp = client.post("/api/sessions/does-not-exist/schedule")
    assert resp.status_code == 404


def test_remove_from_schedule(client):
    client.post("/api/events/Summit-Toronto-2025/select")
    client.post("/api/sessions/AIM102-S/schedule")
    resp = client.delete("/api/sessions/AIM102-S/schedule")
    assert resp.json()["scheduleSessionIds"] == []


def test_add_note_and_list_notes(client):
    client.post("/api/events/Summit-Toronto-2025/select")
    client.post("/api/sessions/AIM102-S/schedule")
    resp = client.post("/api/notes", json={"session_id": "AIM102-S", "text": "Great talk.", "recording_url": None})
    assert resp.status_code == 200

    resp = client.get("/api/notes")
    notes = resp.json()
    assert len(notes) == 1
    assert notes[0]["sessionId"] == "AIM102-S"
    assert notes[0]["text"] == "Great talk."
    assert notes[0]["recordingUrl"] is None


def test_add_note_with_recording_url(client):
    client.post("/api/events/Summit-Toronto-2025/select")
    client.post("/api/sessions/AIM102-S/schedule")
    client.post(
        "/api/notes",
        json={"session_id": "AIM102-S", "text": "Great talk.", "recording_url": "https://example.com/video"},
    )
    notes = client.get("/api/notes").json()
    assert notes[0]["recordingUrl"] == "https://example.com/video"


def test_add_note_for_unknown_session_returns_404(client):
    client.post("/api/events/Summit-Toronto-2025/select")
    resp = client.post("/api/notes", json={"session_id": "does-not-exist", "text": "x"})
    assert resp.status_code == 404


def test_generate_trip_report_uses_real_schedule_and_notes(client):
    client.post("/api/events/Summit-Toronto-2025/select")
    client.post("/api/sessions/AIM102-S/schedule")
    client.post("/api/notes", json={"session_id": "AIM102-S", "text": "Great talk."})

    resp = client.post("/api/reports/trip-report", json={"attendee_name": "Jane Doe"})
    assert resp.status_code == 200
    body = resp.json()
    assert "Jane Doe" in body["markdown"]
    assert "AI That Pays Off" in body["markdown"]
    assert "Great talk." in body["markdown"]
    assert "<h1>" in body["html"]


def test_generate_linkedin_draft_includes_real_hashtags(client):
    client.post("/api/events/Summit-Toronto-2025/select")
    client.post("/api/sessions/AIM102-S/schedule")
    client.post("/api/notes", json={"session_id": "AIM102-S", "text": "Great talk."})

    resp = client.post("/api/reports/linkedin", json={"attendee_name": "Jane"})
    assert resp.status_code == 200
    assert "#GenerativeAI" in resp.json()["markdown"]


def test_generate_builder_center_draft_includes_untouched_sessions(client):
    client.post("/api/events/Summit-Toronto-2025/select")
    client.post("/api/sessions/AIM102-S/schedule")
    client.post("/api/sessions/DAT302/schedule")
    client.post("/api/notes", json={"session_id": "AIM102-S", "text": "Great talk."})

    resp = client.post("/api/reports/builder-center", json={"attendee_name": "Jane"})
    md = resp.json()["markdown"]
    assert "## Also on the agenda" in md
    assert "Build a cost-effective RAG-based gen AI application" in md


def test_two_browser_sessions_do_not_share_state(client):
    c1 = TestClient(server_module.app)
    c2 = TestClient(server_module.app)

    c1.post("/api/events/Summit-Toronto-2025/select")
    c1.post("/api/sessions/AIM102-S/schedule")

    c2.post("/api/events/Summit-Toronto-2025/select")
    resp = c2.get("/api/schedule")
    assert resp.json() == []  # c2 never added AIM102-S, so its schedule stays empty
