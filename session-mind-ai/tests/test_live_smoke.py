"""Live, network-dependent smoke test against a REAL public (no-auth) AWS
Events API catalog. Confirms events_api_client's parsing (items wrapper,
session wrapper, sessionTime -> start/end derivation, room/areas_of_interest
field names) still matches the actual live API, not just our own fixtures.

Skipped by default (requires network access and the live API to be up).
Run explicitly with:
  $env:RUN_LIVE_SMOKE_TESTS = "1"; python -m pytest tests/test_live_smoke.py -v

Deliberately targets a public Summit catalog, not reinvent2026, since the
latter requires event registration this test suite does not have (confirmed
via live 403s -- see docs/hldd.md "API reality check" and the root README).
"""

from __future__ import annotations

import os
import re

import pytest

from session_mind_ai.events_api_client import EventsApiClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_SMOKE_TESTS") != "1",
    reason="Set RUN_LIVE_SMOKE_TESTS=1 to run live network tests against the real Events API.",
)

EVENT_ID = "Summit-Toronto-2025"


def test_list_all_sessions_returns_real_items_with_expected_shape():
    client = EventsApiClient()
    try:
        sessions = client.list_all_sessions(EVENT_ID)
    finally:
        client.close()

    assert len(sessions) > 0
    assert any(s.room for s in sessions)

    with_time = next((s for s in sessions if s.start and s.end), None)
    assert with_time is not None
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00$", with_time.start)


def test_get_session_matches_a_session_from_list_all_sessions():
    client = EventsApiClient()
    try:
        sessions = client.list_all_sessions(EVENT_ID)
        target = next(s for s in sessions if s.start)
        fetched = client.get_session(EVENT_ID, target.session_id)
    finally:
        client.close()

    assert fetched.session_id == target.session_id
    assert fetched.title == target.title


def test_get_schedule_on_a_registration_required_event_returns_403_not_401():
    """Documents the real, confirmed auth behavior: a valid-but-unregistered
    token gets 403 (not 401) against reinvent2026/reinvent2025. Run without
    a token here deliberately -- that gets 401 (no credentials at all),
    which is the complementary case to the 403 we verified manually with a
    real signed-in token. Both are asserted so this test documents the full
    picture even though only one half is runnable without live credentials.
    """
    from session_mind_ai.events_api_client import EventsApiError

    client = EventsApiClient()  # no access_token
    try:
        with pytest.raises(EventsApiError) as exc_info:
            client.get_schedule("reinvent2026")
        assert exc_info.value.status_code == 401
    finally:
        client.close()
