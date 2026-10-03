"""Social/blog draft generation for a trip report.

Builds a LinkedIn post draft and an AWS Builder Center blog post draft
from the exact same `TripReportSection` list that `trip_report.py` uses --
real session titles/abstracts/taxonomy from the catalog, and the
attendee's own real notes. No fabricated metrics, job titles, employer
names, or claims about outcomes are generated; placeholders are left as
editable bracketed text (e.g. "[your takeaway]") wherever the attendee's
own voice/context is genuinely required and cannot be inferred from the
Events API.

Like briefing.py and trip_report.py, this is template-based and
deterministic, not an LLM call -- fully unit-testable without network
access, and the "generation" half (more natural prose) is a documented
extension point for a future Bedrock-backed pass over this same
real-data retrieval.
"""

from __future__ import annotations

import re

from .trip_report import TripReportSection

# LinkedIn has no hard limit worth coding against, but very long posts get
# truncated in-feed; keep hashtags to a reasonable, skimmable count instead
# of dumping every taxonomy tag across every session.
MAX_HASHTAGS = 6


def _attended_sections(sections: list[TripReportSection]) -> list[TripReportSection]:
    """Sections with at least one attendee note -- the same "actually has
    something to say" filter trip_report.render_markdown uses for its
    per-session headings."""
    return [s for s in sections if s.notes]


def _collect_hashtags(sections: list[TripReportSection]) -> list[str]:
    """Real taxonomy tags (areas_of_interest, then topics as a fallback)
    from attended sessions, deduplicated, order-preserved, converted to
    hashtag form (e.g. "Generative AI" -> "#GenerativeAI")."""
    seen: dict[str, None] = {}
    for section in sections:
        tags = section.session.areas_of_interest or section.session.topics
        for tag in tags:
            seen.setdefault(tag, None)
    hashtags = []
    for tag in seen:
        compact = _to_hashtag_case(tag)
        if compact:
            hashtags.append(f"#{compact}")
        if len(hashtags) >= MAX_HASHTAGS:
            break
    return hashtags


def _to_hashtag_case(tag: str) -> str:
    """Converts a real taxonomy tag like "Generative AI" into hashtag case
    ("GenerativeAI"), preserving existing acronyms (e.g. "AI", "AWS")
    rather than lowercasing them the way str.title() would ("GenerativeAi").
    """
    words = re.findall(r"[A-Za-z0-9]+", tag)
    cased = [w if w.isupper() else w.capitalize() for w in words]
    return "".join(cased)


def _first_note_text(section: TripReportSection) -> str | None:
    if not section.notes:
        return None
    return sorted(section.notes, key=lambda n: n.created_at)[0].text.strip()


def build_linkedin_draft(
    sections: list[TripReportSection],
    attendee_name: str = "Attendee",
    event_name: str = "the event",
) -> str:
    """Builds a short, skimmable LinkedIn post draft.

    Pulls real session titles and the attendee's own first note per
    session as the "highlight" line -- never a fabricated takeaway. If a
    session has no note text to quote, it's omitted from the highlights
    list rather than inventing one.
    """
    attended = _attended_sections(sections)
    hashtags = _collect_hashtags(sections)

    lines: list[str] = []
    lines.append(f"Just wrapped up {event_name}! 🎉")
    lines.append("")
    if attended:
        lines.append(
            f"Attended {len(attended)} session(s) and walked away with some great takeaways. A few highlights:"
        )
        lines.append("")
        for section in attended[:5]:  # keep the post skimmable
            note_text = _first_note_text(section)
            if note_text:
                lines.append(f"🔹 {section.session.title} — {note_text}")
            else:
                lines.append(f"🔹 {section.session.title}")
        lines.append("")
    else:
        lines.append("[Add a highlight or two from the sessions you attended here.]")
        lines.append("")

    lines.append("[Add your own closing thought here -- what you're most excited to try next.]")
    lines.append("")
    if hashtags:
        lines.append(" ".join(hashtags) + " #AWSCommunity #AWS")
    else:
        lines.append("#AWSCommunity #AWS")

    return "\n".join(lines).strip() + "\n"


def build_builder_center_draft(
    sections: list[TripReportSection],
    attendee_name: str = "Attendee",
    event_name: str = "the event",
) -> str:
    """Builds a longer, structured Builder Center blog post draft in
    Markdown. Each attended session gets its own subsection with the real
    catalog abstract plus the attendee's real notes -- the same underlying
    data as the trip report, reformatted for a blog audience rather than a
    personal recap."""
    attended = _attended_sections(sections)
    untouched = [s.session.title for s in sections if not s.notes]
    hashtags = _collect_hashtags(sections)

    lines: list[str] = []
    lines.append(f"# My {event_name} Recap")
    lines.append("")
    lines.append(
        f"[Add 1-2 sentences introducing yourself and why you attended {event_name}.]"
    )
    lines.append("")

    if attended:
        lines.append("## Sessions that stood out")
        lines.append("")
        for section in attended:
            s = section.session
            lines.append(f"### {s.title}")
            if s.abstract:
                lines.append(f"> {s.abstract.strip()}")
                lines.append("")
            lines.append("**My takeaway:**")
            for note in sorted(section.notes, key=lambda n: n.created_at):
                lines.append(f"- {note.text.strip()}")
            recording_links = [n.recording_url for n in section.notes if n.recording_url]
            for url in dict.fromkeys(recording_links):
                lines.append(f"- Recording: {url}")
            lines.append("")

    if untouched:
        lines.append("## Also on the agenda")
        lines.append(
            "I didn't get a chance to capture detailed notes on these, but they're worth a look if you're "
            "exploring similar topics:"
        )
        lines.append("")
        for title in untouched:
            lines.append(f"- {title}")
        lines.append("")

    lines.append("## Closing thoughts")
    lines.append("[Add your own closing thoughts and what you're planning to build/try next.]")
    lines.append("")

    if hashtags:
        lines.append("**Tags:** " + ", ".join(h.lstrip("#") for h in hashtags))
        lines.append("")

    return "\n".join(lines).strip() + "\n"
