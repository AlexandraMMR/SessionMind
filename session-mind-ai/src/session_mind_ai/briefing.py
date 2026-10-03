"""Pre-session briefing generation.

Builds the "3-bullet prep card" described in the HLDD from a Session's own
metadata plus optional supporting documentation snippets (typically sourced
from the AWS Knowledge MCP server via knowledge_client.search_documentation).

No LLM call is made here by default -- the template-based summary below is
deterministic and testable without network access or Bedrock credentials.
`Bedrock AgentCore` integration point is `render_with_bedrock`, which is a
thin optional wrapper that a deployment can swap in once model access is
configured; it is not exercised by the unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass

from .events_api_client import Session


@dataclass
class PrepCard:
    session_id: str
    title: str
    bullets: list[str]
    doc_links: list[str]


def build_prep_card(session: Session, doc_snippets: list[dict] | None = None) -> PrepCard:
    """Builds a deterministic 3-bullet prep card.

    Bullet 1: what the session is about (from abstract/level/areas of interest).
    Bullet 2: prerequisite concepts, derived from topics taxonomy.
    Bullet 3: a pointer to further reading, from doc_snippets if supplied.

    Note: there is no `tracks` field in the real catalog (see
    events_api_client.Session docstring); `areas_of_interest` is the real
    closest equivalent and is used here instead.
    """
    bullets: list[str] = []

    level_note = f" (level {session.level})" if session.level else ""
    area_note = f" in {', '.join(session.areas_of_interest)}" if session.areas_of_interest else ""
    bullets.append(f"{session.title}{level_note}{area_note}: {_summarize_abstract(session.abstract)}")

    if session.topics:
        bullets.append("Prerequisite concepts to skim beforehand: " + ", ".join(session.topics[:5]) + ".")
    else:
        bullets.append("No taxonomy topics published for this session yet; review the abstract above.")

    doc_links = [d["url"] for d in (doc_snippets or []) if d.get("url")]
    if doc_snippets:
        top = doc_snippets[0]
        bullets.append(f"Related docs: {top.get('title', top.get('url', 'see link'))}")
    else:
        bullets.append("No related AWS documentation was found for this session's topics.")

    return PrepCard(session_id=session.session_id, title=session.title, bullets=bullets, doc_links=doc_links)


def _summarize_abstract(abstract: str | None, max_len: int = 220) -> str:
    if not abstract:
        return "No abstract published yet."
    trimmed = abstract.strip()
    if len(trimmed) <= max_len:
        return trimmed
    return trimmed[: max_len - 1].rsplit(" ", 1)[0] + "\u2026"
