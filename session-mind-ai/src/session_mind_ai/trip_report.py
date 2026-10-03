"""Post-conference trip report synthesis.

Pairs attendee notes (from NotesStore) with official session metadata
(from EventsApiClient) and formats a structured Markdown executive
summary, per the HLDD's "Post-Session Phase".

As with briefing.py, the default implementation is template-based and
deterministic so it is unit-testable without live Bedrock access. A
Bedrock AgentCore-backed synthesis path can layer on top of
`build_trip_report_sections` by feeding its output as grounding context to
a model prompt -- the RAG "retrieval" half of the pipeline is exactly
`build_trip_report_sections`; only the "generation" half needs the model.
"""

from __future__ import annotations

from dataclasses import dataclass

from .events_api_client import Session
from .notes_store import Note


@dataclass
class TripReportSection:
    session: Session
    notes: list[Note]


def build_trip_report_sections(sessions: list[Session], notes: list[Note]) -> list[TripReportSection]:
    notes_by_session: dict[str, list[Note]] = {}
    for note in notes:
        notes_by_session.setdefault(note.session_id, []).append(note)

    sections = [
        TripReportSection(session=s, notes=notes_by_session.get(s.session_id, []))
        for s in sessions
    ]
    # Sessions with notes first (most relevant to a trip report), then chronological.
    sections.sort(key=lambda sec: (len(sec.notes) == 0, sec.session.start or ""))
    return sections


def render_markdown(sections: list[TripReportSection], attendee_name: str = "Attendee") -> str:
    lines = [f"# re:Invent Trip Report — {attendee_name}", ""]
    attended = [s for s in sections if s.notes]
    lines.append(f"**Sessions with captured notes:** {len(attended)} of {len(sections)} reserved sessions.")
    lines.append("")

    for section in sections:
        if not section.notes:
            continue
        s = section.session
        lines.append(f"## {s.title}")
        meta_bits = [b for b in [s.abbreviation, s.level, s.room] if b]
        if meta_bits:
            lines.append(f"*{' · '.join(meta_bits)}*")
        lines.append("")

        # Real session abstract from the catalog, for context without
        # needing to re-fetch the session separately.
        if s.abstract:
            lines.append(s.abstract.strip())
            lines.append("")

        for note in sorted(section.notes, key=lambda n: n.created_at):
            lines.append(f"- {note.text.strip()}")
        lines.append("")

        # Attendee-supplied recording links only -- never auto-discovered.
        # The Events API has no recording-URL field on a session at all,
        # and automatically matching a session title against YouTube would
        # risk silently attaching the wrong talk's video to the wrong
        # session, which is worse than attaching nothing in a report whose
        # value is accuracy. See notes_store.Note.recording_url.
        recording_links = [n.recording_url for n in section.notes if n.recording_url]
        if recording_links:
            lines.append("**Recording:**")
            for url in dict.fromkeys(recording_links):  # de-duplicate, preserve order
                lines.append(f"- {url}")
            lines.append("")

    untouched = [s.session.title for s in sections if not s.notes]
    if untouched:
        lines.append("## Reserved but no notes captured")
        for title in untouched:
            lines.append(f"- {title}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"
