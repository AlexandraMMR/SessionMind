"""SessionMind AI -- recordable demo script.

Runs ENTIRELY against the real AWS Events API, no mocks, no overlays,
no registration required. Unlike the other two modules, SessionMind's
MCP tools never touch GetSchedule or CreatePersonalTime -- it only ever
reads ListSessions/GetSession (both public) and writes notes to its own
local store -- so this demo needs no illustrative overlay at all.

Flow:
  1. ListSessions on a real, public event catalog.
  2. GetSession on a handful of real sessions.
  3. build_prep_card() -- the real pre-session briefing logic -- against
     real session metadata (AWS Knowledge MCP lookup included; degrades
     gracefully if that server is unreachable, same as production).
  4. record_session_note() equivalent -- store a couple of notes against
     real session IDs.
  5. generate_trip_report() equivalent -- render the real Markdown
     synthesis over the real sessions + the notes just recorded, AND
     write it to a real .md file under scripts/output/ (this is the
     actual deliverable `generate_trip_report` produces in production --
     printing it to the terminal alone undersells the point of a
     Markdown executive summary meant to be opened/shared/attached).
  6. generate_linkedin_draft() / generate_builder_center_draft() --
     built from the exact same real sessions + real notes, also written
     to scripts/output/. Closing-thought lines are left as editable
     placeholders since they require the attendee's own voice -- nothing
     here fabricates a personal opinion or an outcome metric.

Run with:
  python scripts/demo.py
  python scripts/demo.py Summit-Dubai-2025
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from session_mind_ai.briefing import build_prep_card
from session_mind_ai.events_api_client import EventsApiClient
from session_mind_ai.knowledge_client import search_documentation
from session_mind_ai.notes_store import InMemoryNotesStore, Note
from session_mind_ai.social_drafts import build_builder_center_draft, build_linkedin_draft
from session_mind_ai.trip_report import build_trip_report_sections, render_markdown

DEFAULT_EVENT_ID = "Summit-Toronto-2025"
OUTPUT_DIR = Path(__file__).parent / "output"


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    event_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EVENT_ID

    section(f"SessionMind AI demo -- live catalog: {event_id}")
    print("Calling the REAL AWS Events API (ListSessions/GetSession), no credentials, no mocks.")

    client = EventsApiClient()  # no token -- this event is public
    try:
        all_sessions = client.list_all_sessions(event_id)
        print(f"\nFetched {len(all_sessions)} real sessions from {event_id}.")

        with_taxonomy = [s for s in all_sessions if s.topics or s.areas_of_interest]
        print(f"{len(with_taxonomy)} of them have real topic/area-of-interest taxonomy.")

        # ------------------------------------------------------------------
        # Pre-session briefing (fully real, including the GetSession round trip)
        # ------------------------------------------------------------------
        section("PRE-SESSION BRIEFING -- real GetSession + real AWS Knowledge MCP lookup")

        chosen = with_taxonomy[:3] if with_taxonomy else all_sessions[:3]
        cards = []
        for s in chosen:
            fresh = client.get_session(event_id, s.session_id)  # real GetSession round trip
            print(f"\nGetSession({fresh.session_id}) -> real title: \"{fresh.title}\"")

            doc_query = " ".join(fresh.topics or [fresh.title])
            print(f"Querying the real AWS Knowledge MCP server for: \"{doc_query}\"")
            try:
                doc_snippets = asyncio.run(search_documentation(doc_query))
            except Exception as exc:  # noqa: BLE001 - same best-effort fallback as production
                print(f"  (AWS Knowledge MCP lookup failed, degrading gracefully: {exc})")
                doc_snippets = []
            print(f"  {len(doc_snippets)} doc snippet(s) returned.")

            card = build_prep_card(fresh, doc_snippets)
            cards.append(card)
            print("Prep card:")
            for i, bullet in enumerate(card.bullets, start=1):
                print(f"  {i}. {bullet}")

        # ------------------------------------------------------------------
        # Note capture (local store -- the one piece that never touches the API)
        # ------------------------------------------------------------------
        section("NOTE CAPTURE -- bound to real session IDs")
        print(
            "The AWS Events API has no recording-URL field on a session at all, and most AWS\n"
            "Summit talks are never individually posted online, so a recording link is only ever\n"
            "attached if the attendee supplies one themselves -- never auto-discovered or\n"
            "auto-matched by title. The one example below is a clearly fictional placeholder URL,\n"
            "standing in for a real link an attendee would paste in."
        )
        notes_store = InMemoryNotesStore()
        sample_notes = [
            ("Great concrete example in the talk, worth re-watching the recording.", "https://example.com/placeholder-recording-link"),
            ("Follow up: check if this pattern applies to our own account structure.", None),
        ]
        for i, (note_text, recording_url) in enumerate(sample_notes):
            target = chosen[i % len(chosen)]
            notes_store.add_note(
                Note(session_id=target.session_id, text=note_text, author="demo-attendee", recording_url=recording_url)
            )
            url_suffix = f', recording_url="{recording_url}"' if recording_url else ""
            print(f'record_session_note("{target.session_id}", "{note_text}"{url_suffix})')

        # ------------------------------------------------------------------
        # Trip report synthesis (real sessions + real notes just recorded)
        # ------------------------------------------------------------------
        section("TRIP REPORT -- real session metadata + the notes just recorded")
        all_notes = notes_store.all_notes()
        sections_ = build_trip_report_sections(chosen, all_notes)
        markdown = render_markdown(sections_, attendee_name="Demo Attendee")
        print(markdown)

        OUTPUT_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = OUTPUT_DIR / f"trip-report-{event_id}-{timestamp}.md"
        output_path.write_text(markdown, encoding="utf-8")
        print(f"\nWrote the real Markdown trip report to: {output_path.resolve()}")

        # ------------------------------------------------------------------
        # Social/blog draft generation (same real data, reformatted)
        # ------------------------------------------------------------------
        section("SOCIAL DRAFTS -- same real sessions + notes, drafted for LinkedIn and a blog post")
        event_display_name = event_id.replace("-", " ")

        linkedin_draft = build_linkedin_draft(sections_, attendee_name="Demo Attendee", event_name=event_display_name)
        print("\n--- LinkedIn draft ---\n")
        print(linkedin_draft)
        linkedin_path = OUTPUT_DIR / f"linkedin-draft-{event_id}-{timestamp}.md"
        linkedin_path.write_text(linkedin_draft, encoding="utf-8")
        print(f"Wrote the LinkedIn draft to: {linkedin_path.resolve()}")

        builder_center_draft = build_builder_center_draft(
            sections_, attendee_name="Demo Attendee", event_name=event_display_name
        )
        print("\n--- AWS Builder Center blog draft ---\n")
        print(builder_center_draft)
        builder_center_path = OUTPUT_DIR / f"builder-center-draft-{event_id}-{timestamp}.md"
        builder_center_path.write_text(builder_center_draft, encoding="utf-8")
        print(f"Wrote the Builder Center draft to: {builder_center_path.resolve()}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
