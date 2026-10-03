from session_mind_ai.briefing import build_prep_card
from session_mind_ai.events_api_client import Session


def make_session(**overrides) -> Session:
    defaults = dict(
        session_id="s1",
        title="Serverless Patterns at Scale",
        abstract="A deep dive into event-driven serverless architectures on AWS, covering Lambda, "
        "EventBridge, and Step Functions with real production case studies from enterprise customers.",
        level="300 – Advanced",
        areas_of_interest=["Serverless"],
        topics=["Lambda", "EventBridge", "Step Functions"],
    )
    defaults.update(overrides)
    return Session(**defaults)


def test_build_prep_card_has_three_bullets():
    card = build_prep_card(make_session())
    assert card.session_id == "s1"
    assert len(card.bullets) == 3


def test_first_bullet_includes_level_and_area_of_interest():
    card = build_prep_card(make_session())
    assert "300" in card.bullets[0]
    assert "Serverless" in card.bullets[0]


def test_second_bullet_lists_topics():
    card = build_prep_card(make_session())
    assert "Lambda" in card.bullets[1]
    assert "EventBridge" in card.bullets[1]


def test_handles_missing_topics_gracefully():
    card = build_prep_card(make_session(topics=[]))
    assert "No taxonomy topics" in card.bullets[1]


def test_handles_missing_abstract_gracefully():
    card = build_prep_card(make_session(abstract=None))
    assert "No abstract published" in card.bullets[0]


def test_doc_snippets_populate_third_bullet_and_links():
    doc_snippets = [{"title": "Lambda Developer Guide", "url": "https://docs.aws.amazon.com/lambda/"}]
    card = build_prep_card(make_session(), doc_snippets=doc_snippets)
    assert "Lambda Developer Guide" in card.bullets[2]
    assert card.doc_links == ["https://docs.aws.amazon.com/lambda/"]


def test_long_abstract_is_truncated():
    long_abstract = "word " * 100
    card = build_prep_card(make_session(abstract=long_abstract))
    assert len(card.bullets[0]) < len(long_abstract)
    assert card.bullets[0].endswith("\u2026")
