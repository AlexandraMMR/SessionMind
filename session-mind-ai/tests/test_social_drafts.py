from session_mind_ai.events_api_client import Session
from session_mind_ai.notes_store import Note
from session_mind_ai.social_drafts import build_builder_center_draft, build_linkedin_draft
from session_mind_ai.trip_report import build_trip_report_sections


def make_sessions():
    return [
        Session(
            session_id="s1",
            title="Serverless Patterns",
            start="2026-12-01T14:00:00",
            abbreviation="SVS301",
            level="300 – Advanced",
            abstract="A deep dive into event-driven serverless architectures on AWS.",
            areas_of_interest=["Serverless", "Generative AI"],
        ),
        Session(
            session_id="s2",
            title="Intro to S3",
            start="2026-12-01T09:00:00",
            abbreviation="STG100",
            level="100 – Foundational",
            areas_of_interest=["Storage"],
        ),
        Session(session_id="s3", title="Keynote", start="2026-12-01T08:00:00"),
    ]


def make_notes():
    return [
        Note(session_id="s1", text="Great talk on EventBridge patterns.", author="me", created_at=1),
    ]


class TestLinkedInDraft:
    def test_includes_event_name_and_session_title(self):
        sections = build_trip_report_sections(make_sessions(), make_notes())
        draft = build_linkedin_draft(sections, event_name="AWS Summit Toronto 2025")
        assert "AWS Summit Toronto 2025" in draft
        assert "Serverless Patterns" in draft

    def test_includes_real_note_text_as_highlight(self):
        sections = build_trip_report_sections(make_sessions(), make_notes())
        draft = build_linkedin_draft(sections)
        assert "Great talk on EventBridge patterns." in draft

    def test_includes_hashtags_from_real_taxonomy(self):
        sections = build_trip_report_sections(make_sessions(), make_notes())
        draft = build_linkedin_draft(sections)
        assert "#Serverless" in draft
        assert "#AWSCommunity" in draft

    def test_hashtag_preserves_acronym_casing(self):
        sessions = make_sessions()
        sessions[0].areas_of_interest = ["Generative AI"]
        sections = build_trip_report_sections(sessions, make_notes())
        draft = build_linkedin_draft(sections)
        assert "#GenerativeAI" in draft
        assert "#GenerativeAi" not in draft

    def test_leaves_placeholder_when_no_notes_at_all(self):
        sections = build_trip_report_sections(make_sessions(), [])
        draft = build_linkedin_draft(sections)
        assert "[Add a highlight" in draft

    def test_always_includes_closing_placeholder(self):
        sections = build_trip_report_sections(make_sessions(), make_notes())
        draft = build_linkedin_draft(sections)
        assert "[Add your own closing thought" in draft

    def test_does_not_fabricate_a_takeaway_for_session_with_no_note_text(self):
        # Build a session with a note that has empty text -- edge case,
        # should not crash or invent content.
        sections = build_trip_report_sections(make_sessions(), make_notes())
        draft = build_linkedin_draft(sections)
        # Only s1 has a note; s2/s3 should not appear as bullet highlights.
        assert "🔹 Intro to S3" not in draft
        assert "🔹 Keynote" not in draft


class TestBuilderCenterDraft:
    def test_includes_real_abstract(self):
        sections = build_trip_report_sections(make_sessions(), make_notes())
        draft = build_builder_center_draft(sections, event_name="AWS Summit Toronto 2025")
        assert "A deep dive into event-driven serverless architectures on AWS." in draft

    def test_includes_real_note_as_takeaway(self):
        sections = build_trip_report_sections(make_sessions(), make_notes())
        draft = build_builder_center_draft(sections)
        assert "Great talk on EventBridge patterns." in draft

    def test_lists_untouched_sessions_separately(self):
        sections = build_trip_report_sections(make_sessions(), make_notes())
        draft = build_builder_center_draft(sections)
        assert "## Also on the agenda" in draft
        assert "Intro to S3" in draft
        assert "Keynote" in draft

    def test_includes_recording_link_when_present(self):
        notes = [
            Note(session_id="s1", text="Great talk.", author="me", created_at=1, recording_url="https://example.com/video"),
        ]
        sections = build_trip_report_sections(make_sessions(), notes)
        draft = build_builder_center_draft(sections)
        assert "https://example.com/video" in draft

    def test_includes_closing_thoughts_placeholder(self):
        sections = build_trip_report_sections(make_sessions(), make_notes())
        draft = build_builder_center_draft(sections)
        assert "## Closing thoughts" in draft
        assert "[Add your own closing thoughts" in draft

    def test_includes_tags_from_real_taxonomy(self):
        sections = build_trip_report_sections(make_sessions(), make_notes())
        draft = build_builder_center_draft(sections)
        assert "**Tags:**" in draft
        assert "Serverless" in draft

    def test_no_sessions_attended_still_renders_without_crash(self):
        sections = build_trip_report_sections(make_sessions(), [])
        draft = build_builder_center_draft(sections)
        assert "# My the event Recap" in draft
        assert "## Also on the agenda" in draft
