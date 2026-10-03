"""Thin, typed REST client for the real AWS Events API.

Mirrors the operations documented at
https://docs.aws.amazon.com/events/latest/devguide/rest-api.html

Only the read operations SessionMind needs are wrapped: ListEvents,
GetSchedule, ListSessions (paginated), GetSession. SessionMind never
writes to a schedule, so no mutating operations are included here.

We use the REST surface (not the official MCP server) for this client
because the browser-interactive sign-in flow required by the MCP server on
every call is impractical for an unattended EventBridge-triggered worker.
See docs/adr/ADR-002 for the full reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.awsevents.com"


class EventsApiError(RuntimeError):
    def __init__(self, status_code: int, operation: str, body: str) -> None:
        super().__init__(f"EventsApi {operation} failed with HTTP {status_code}: {body[:500]}")
        self.status_code = status_code
        self.operation = operation


def _derive_session_times(session_time: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """Combines sessionTime.date + time into a naive-local ISO start string,
    and adds `length` minutes for the end. NOT real IANA-timezone-aware math
    -- sessionTime.timezone is read by callers but not applied here. See
    Session docstring and docs/hldd.md "API reality check" for the full
    rationale and limitation.
    """
    if not session_time:
        return None, None
    date = session_time.get("date")
    time = session_time.get("time")
    if not date or not time:
        return None, None
    start = f"{date}T{time}:00"
    length_raw = session_time.get("length")
    end = None
    if length_raw is not None:
        try:
            length_minutes = int(length_raw)
        except (TypeError, ValueError):
            length_minutes = None
        if length_minutes is not None:
            from datetime import datetime, timedelta

            start_dt = datetime.fromisoformat(start)
            end_dt = start_dt + timedelta(minutes=length_minutes)
            end = end_dt.strftime("%Y-%m-%dT%H:%M:00")
    return start, end


@dataclass
class Session:
    """Mirrors the real session shape returned by ListSessions/GetSession,
    confirmed live against public (no-auth) catalogs (e.g. Summit-Toronto-2025)
    on 2026-10-03 -- NOT the devguide's paraphrased field list. Key
    corrections versus the original design: the real abbreviation field is
    `abbreviation`, not `sessionCode`; there is no `tracks` field anywhere
    (real taxonomy is `topics`/`areas_of_interest`/`industries`/`roles`/
    `services`); there is no separate `venue` field, only `room`; and there
    is no `start`/`end` ISO field -- those are synthesized here from the
    real `sessionTime: {date, time, length, timezone}` shape via
    `_derive_session_times`.
    """

    session_id: str
    title: str
    abstract: str | None = None
    abbreviation: str | None = None
    type: str | None = None
    level: str | None = None
    room: str | None = None
    is_all_day_session: bool = False
    topics: list[str] = field(default_factory=list)
    areas_of_interest: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    start: str | None = None
    end: str | None = None
    speakers: list[str] = field(default_factory=list)

    @staticmethod
    def from_raw(raw: dict[str, Any]) -> "Session":
        start, end = _derive_session_times(raw.get("sessionTime"))
        return Session(
            session_id=raw["sessionId"],
            title=raw.get("title", "(untitled)"),
            abstract=raw.get("abstract"),
            abbreviation=raw.get("abbreviation"),
            type=raw.get("type"),
            level=raw.get("level"),
            room=raw.get("room"),
            is_all_day_session=bool(raw.get("isAllDaySession", False)),
            topics=list(raw.get("topics") or []),
            areas_of_interest=list(raw.get("areasOfInterest") or []),
            industries=list(raw.get("industries") or []),
            roles=list(raw.get("roles") or []),
            services=list(raw.get("services") or []),
            start=start,
            end=end,
            # Real speaker entries are {"name": "Person, Org"} objects, not bare strings.
            speakers=[s.get("name", "") for s in (raw.get("speakers") or []) if isinstance(s, dict)],
        )


@dataclass
class ScheduleEntry:
    session_id: str | None
    title: str | None
    start_date_time: str | None
    end_date_time: str | None
    kind: str  # "reservation" | "favorite" | "personal-time"


@dataclass
class EventSummary:
    """Mirrors the real ListEvents item shape, confirmed live by calling
    `GET /v1/events` directly (no auth needed for this one operation) --
    e.g. `{"eventId": "reinvent2026", "name": "re:Invent 2026",
    "authenticationRequired": true, "startDate": "...", "endDate": "..."}`.
    `authenticationRequired` is the real field that determines whether an
    event's session catalog is public: a public (false) event can be
    browsed with ListSessions/GetSession with no token at all, which is
    what the web demo relies on to avoid needing a registered attendee.
    """

    event_id: str
    name: str
    authentication_required: bool
    start_date: str | None = None
    end_date: str | None = None

    @staticmethod
    def from_raw(raw: dict[str, Any]) -> "EventSummary":
        return EventSummary(
            event_id=raw["eventId"],
            name=raw.get("name", raw["eventId"]),
            authentication_required=bool(raw.get("authenticationRequired", False)),
            start_date=raw.get("startDate"),
            end_date=raw.get("endDate"),
        )


class EventsApiClient:
    """Synchronous httpx-based client. Safe to use from Lambda handlers."""

    def __init__(
        self,
        access_token: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=15.0)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def _request(self, operation: str, method: str, path: str) -> Any:
        resp = self._client.request(method, f"{self._base_url}{path}", headers=self._headers())
        if resp.status_code >= 400:
            raise EventsApiError(resp.status_code, operation, resp.text)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def list_events(self, include_past: bool = False) -> list[EventSummary]:
        """GET /v1/events -- no auth required for any event, confirmed live.

        Used by the web demo to let a visitor pick a real, currently-public
        (authenticationRequired=false) event to browse, instead of
        hardcoding one event ID.
        """
        query = "?includePast=true" if include_past else ""
        page = self._request("ListEvents", "GET", f"/v1/events{query}") or {}
        return [EventSummary.from_raw(e) for e in page.get("items", [])]

    def get_schedule(self, event_id: str) -> dict[str, Any]:
        """GET /v1/events/{eventId}/schedule -- reservations, favorites, personal time."""
        return self._request("GetSchedule", "GET", f"/v1/events/{event_id}/schedule") or {}

    def get_session(self, event_id: str, session_id: str) -> Session:
        """GET /v1/events/{eventId}/sessions/{sessionId}

        The real response wraps the session object in a `session` key
        (confirmed live), unlike a flat ListSessions item.
        """
        raw = self._request("GetSession", "GET", f"/v1/events/{event_id}/sessions/{session_id}")
        return Session.from_raw(raw["session"])

    def list_all_sessions(self, event_id: str, include_abstracts: bool = True) -> list[Session]:
        """GET /v1/events/{eventId}/sessions, following nextToken until absent.

        The real item array comes back as `items`, not `sessions` --
        confirmed against live public catalogs. `nextToken` was never
        observed in practice (even at 166 items in one page) but is still
        handled defensively since the docs warn pagination can occur.
        """
        sessions: list[Session] = []
        next_token: str | None = None
        while True:
            params = []
            if not include_abstracts:
                params.append("includeAbstracts=false")
            if next_token:
                params.append(f"nextToken={next_token}")
            query = f"?{'&'.join(params)}" if params else ""
            page = self._request("ListSessions", "GET", f"/v1/events/{event_id}/sessions{query}") or {}
            sessions.extend(Session.from_raw(s) for s in page.get("items", []))
            next_token = page.get("nextToken")
            if not next_token:
                break
        return sessions

    def close(self) -> None:
        self._client.close()


def upcoming_reservations(schedule: dict[str, Any]) -> list[ScheduleEntry]:
    """Flattens GetSchedule's `reservations` list into ScheduleEntry records.

    Personal time and favorites are intentionally excluded: a briefing only
    makes sense ahead of a *session* the attendee actually reserved.
    """
    entries: list[ScheduleEntry] = []
    for raw in schedule.get("reservations", []) or []:
        entries.append(
            ScheduleEntry(
                session_id=raw.get("sessionId"),
                title=raw.get("title"),
                start_date_time=raw.get("startDateTime"),
                end_date_time=raw.get("endDateTime"),
                kind="reservation",
            )
        )
    return entries
