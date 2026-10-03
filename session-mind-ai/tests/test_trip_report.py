from session_mind_ai.events_api_client import Session
from session_mind_ai.notes_store import Note
from session_mind_ai.trip_report import build_trip_report_sections, render_markdown


def make_sessions():
    return [
        Session(
            session_id="s1",
            title="Serverless Patterns",
            start="2026-12-01T14:00:00",
            abbreviation="SVS301",
            level="300 – Advanced",
            abstract="A deep dive into event-driven serverless architectures on AWS.",
        ),
        Session(session_id="s2", title="Intro to S3", start="2026-12-01T09:00:00", abbreviation="STG100", level="100 – Foundational"),
        Session(session_id="s3", title="Keynote", start="2026-12-01T08:00:00"),
    ]


def make_notes():
    return [
        Note(session_id="s1", text="Great talk on EventBridge patterns.", author="me", created_at=2),
        Note(session_id="s1", text="Ask about cold starts follow-up.", author="me", created_at=1),
    ]


def test_sections_group_notes_by_session():
    sections = build_trip_report_sections(make_sessions(), make_notes())
    s1_section = next(s for s in sections if s.session.session_id == "s1")
    assert len(s1_section.notes) == 2


def test_sections_with_notes_are_sorted_first():
    sections = build_trip_report_sections(make_sessions(), make_notes())
    assert sections[0].session.session_id == "s1"


def test_render_markdown_includes_note_text_and_untouched_sessions():
    sections = build_trip_report_sections(make_sessions(), make_notes())
    md = render_markdown(sections, attendee_name="Jane Doe")

    assert "# re:Invent Trip Report: Jane Doe" in md
    assert "Serverless Patterns" in md
    assert "Ask about cold starts follow-up." in md
    assert "Reserved but no notes captured" in md
    assert "Intro to S3" in md
    assert "Keynote" in md


def test_render_markdown_includes_abbreviation_and_level_as_meta():
    sections = build_trip_report_sections(make_sessions(), make_notes())
    md = render_markdown(sections)
    assert "SVS301" in md
    assert "300 – Advanced" in md


def test_notes_within_a_session_render_chronologically():
    sections = build_trip_report_sections(make_sessions(), make_notes())
    md = render_markdown(sections)
    first_idx = md.index("Ask about cold starts follow-up.")
    second_idx = md.index("Great talk on EventBridge patterns.")
    assert first_idx < second_idx


def test_no_notes_at_all_still_renders_without_error():
    sections = build_trip_report_sections(make_sessions(), [])
    md = render_markdown(sections)
    assert "Sessions with captured notes:** 0 of 3" in md


def test_render_markdown_includes_real_session_abstract():
    sections = build_trip_report_sections(make_sessions(), make_notes())
    md = render_markdown(sections)
    assert "A deep dive into event-driven serverless architectures on AWS." in md


def test_render_markdown_lists_untouched_sessions_with_their_real_titles():
    # s2/s3 have no notes in make_notes(), so they land in the "no notes
    # captured" section rather than getting their own "## " heading.
    sections = build_trip_report_sections(make_sessions(), make_notes())
    md = render_markdown(sections)
    assert "## Intro to S3" not in md
    assert "Intro to S3" in md
    assert "Keynote" in md


def test_render_markdown_includes_abstract_for_untouched_sessions_too():
    # A session with no notes but a real catalog abstract should still
    # show that abstract in the "Reserved but no notes captured" section,
    # not just a bare title.
    sessions = make_sessions()
    sessions[1].abstract = "An introduction to Amazon S3 storage classes."
    sections = build_trip_report_sections(sessions, make_notes())
    md = render_markdown(sections)
    assert "An introduction to Amazon S3 storage classes." in md


def test_render_markdown_handles_untouched_session_with_no_abstract():
    # s3 ("Keynote") has no abstract at all; should list the title without
    # crashing or printing a stray blank/None line.
    sections = build_trip_report_sections(make_sessions(), make_notes())
    md = render_markdown(sections)
    assert "**Keynote**" in md


def test_render_markdown_includes_attendee_supplied_recording_link():
    notes = [
        Note(session_id="s1", text="Great talk.", author="me", created_at=1, recording_url="https://example.com/video"),
    ]
    sections = build_trip_report_sections(make_sessions(), notes)
    md = render_markdown(sections)
    assert "**Recording:**" in md
    assert "https://example.com/video" in md


def test_render_markdown_omits_recording_section_when_no_notes_have_a_url():
    sections = build_trip_report_sections(make_sessions(), make_notes())
    md = render_markdown(sections)
    assert "**Recording:**" not in md


def test_render_markdown_deduplicates_repeated_recording_links():
    notes = [
        Note(session_id="s1", text="First note.", author="me", created_at=1, recording_url="https://example.com/video"),
        Note(session_id="s1", text="Second note.", author="me", created_at=2, recording_url="https://example.com/video"),
    ]
    sections = build_trip_report_sections(make_sessions(), notes)
    md = render_markdown(sections)
    assert md.count("https://example.com/video") == 1
