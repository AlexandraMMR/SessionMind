import httpx
import pytest

from session_mind_ai.events_api_client import (
    EventSummary,
    EventsApiClient,
    EventsApiError,
    Session,
    upcoming_reservations,
)

# Captured live from a real, public (no-auth) AWS Events API catalog
# (Summit-Toronto-2025) on 2026-10-03. See
# ../../fixtures/list_sessions_sample.json for the full capture.
REAL_SESSION_RAW = {
    "sessionId": "AIM102-S",
    "abbreviation": "AIM102-S",
    "title": "AI That Pays Off (sponsored by CGI Inc.)",
    "abstract": "Most AI initiatives stall before they show any value.",
    "type": "Lightning talk",
    "level": "100 – Foundational",
    "isAllDaySession": False,
    "room": "Expo, Athena Theater",
    "areasOfInterest": ["Cost Optimization", "Generative AI"],
    "industries": ["Cross-Industry Solutions"],
    "roles": ["IT Professional / Technical Manager"],
    "services": ["Amazon Bedrock", "Amazon CloudWatch"],
    "topics": ["AI/ML", "Analytics"],
    "speakers": [{"name": "Scott Stanley, CGI Inc."}],
    "sessionTime": {"date": "2025-09-04", "time": "12:30", "length": "30", "timezone": "America/Toronto"},
}


def client_with_transport(handler) -> EventsApiClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://api.awsevents.com")
    return EventsApiClient(access_token="test-token", client=http_client)


def test_get_schedule_sends_bearer_token_and_parses_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.url.path == "/v1/events/reinvent2026/schedule"
        return httpx.Response(200, json={"reservations": [{"sessionId": "s1"}]})

    client = client_with_transport(handler)
    schedule = client.get_schedule("reinvent2026")
    assert schedule["reservations"][0]["sessionId"] == "s1"


def test_get_session_unwraps_real_session_key_and_maps_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"session": REAL_SESSION_RAW})

    client = client_with_transport(handler)
    session = client.get_session("reinvent2026", "AIM102-S")
    assert isinstance(session, Session)
    assert session.title == "AI That Pays Off (sponsored by CGI Inc.)"
    assert session.areas_of_interest == ["Cost Optimization", "Generative AI"]
    assert session.abbreviation == "AIM102-S"
    assert session.speakers == ["Scott Stanley, CGI Inc."]


def test_get_session_derives_start_and_end_from_session_time():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"session": REAL_SESSION_RAW})

    client = client_with_transport(handler)
    session = client.get_session("reinvent2026", "AIM102-S")
    assert session.start == "2025-09-04T12:30:00"
    assert session.end == "2025-09-04T13:00:00"


def test_list_all_sessions_reads_items_not_sessions():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "nextToken" not in str(request.url):
            return httpx.Response(
                200,
                json={"items": [{**REAL_SESSION_RAW, "sessionId": "s1"}], "totalCount": 2, "nextToken": "abc"},
            )
        return httpx.Response(200, json={"items": [{**REAL_SESSION_RAW, "sessionId": "s2"}], "totalCount": 2})

    client = client_with_transport(handler)
    sessions = client.list_all_sessions("reinvent2026")
    assert [s.session_id for s in sessions] == ["s1", "s2"]
    assert len(calls) == 2


def test_list_all_sessions_returns_empty_when_items_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"totalCount": 0})

    client = client_with_transport(handler)
    sessions = client.list_all_sessions("reinvent2026")
    assert sessions == []


def test_error_response_raises_events_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="not registered")

    client = client_with_transport(handler)
    with pytest.raises(EventsApiError) as exc_info:
        client.get_schedule("reinvent2026")
    assert exc_info.value.status_code == 403


def test_list_events_reads_items_and_maps_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/events"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "eventId": "Summit-Toronto-2025",
                        "name": "AWS Summit Toronto 2025",
                        "authenticationRequired": False,
                        "startDate": "2025-09-04T08:00:00.000-04:00",
                        "endDate": "2025-09-04T20:00:00.000-04:00",
                    },
                    {
                        "eventId": "reinvent2026",
                        "name": "re:Invent 2026",
                        "authenticationRequired": True,
                    },
                ]
            },
        )

    client = client_with_transport(handler)
    events = client.list_events()
    assert [e.event_id for e in events] == ["Summit-Toronto-2025", "reinvent2026"]
    assert isinstance(events[0], EventSummary)
    assert events[0].authentication_required is False
    assert events[1].authentication_required is True


def test_list_events_include_past_adds_query_param():
    captured_url = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_url["url"] = str(request.url)
        return httpx.Response(200, json={"items": []})

    client = client_with_transport(handler)
    client.list_events(include_past=True)
    assert "includePast=true" in captured_url["url"]


def test_list_events_returns_empty_when_items_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = client_with_transport(handler)
    assert client.list_events() == []


def test_upcoming_reservations_flattens_schedule():
    schedule = {
        "reservations": [
            {"sessionId": "s1", "title": "A", "startDateTime": "2026-12-01T10:00:00", "endDateTime": "2026-12-01T11:00:00"}
        ],
        "favorites": [{"sessionId": "s2"}],
        "personalTime": [{"personalTimeId": "p1"}],
    }
    entries = upcoming_reservations(schedule)
    assert len(entries) == 1
    assert entries[0].session_id == "s1"
    assert entries[0].kind == "reservation"


class TestSessionFromRaw:
    def test_handles_a_session_with_no_speakers_or_taxonomy(self):
        raw = {"sessionId": "ACT001", "title": "Squid Game VR Challenge", "level": "No Level"}
        session = Session.from_raw(raw)
        assert session.speakers == []
        assert session.topics == []
        assert session.areas_of_interest == []

    def test_handles_a_session_with_no_session_time(self):
        raw = {"sessionId": "ACT001", "title": "No time slot yet"}
        session = Session.from_raw(raw)
        assert session.start is None
        assert session.end is None
