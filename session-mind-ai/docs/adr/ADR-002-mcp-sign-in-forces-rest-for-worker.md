# ADR-002 — Model Context Protocol integration for reasoning, REST for the unattended worker

**Status:** Accepted

## Context

To generate pre-session briefings, SessionMind needs structured access to session metadata and,
separately, grounding documentation from the AWS Knowledge base. Two integration options exist for
the documentation lookup: write a custom scraper/wrapper around AWS documentation search, or
connect to the already-existing, official **AWS Knowledge MCP server**
(`https://knowledge-mcp.global.api.aws`, public, unauthenticated, streamable HTTP).

Separately, for the Events API itself, the official MCP server's requirement of interactive
sign-in on every call (including catalog reads) is incompatible with an EventBridge-triggered
Lambda that must run with nobody watching.

## Decision

1. For AWS documentation grounding: connect directly to the official AWS Knowledge MCP server via
   the `mcp` Python SDK's streamable-HTTP client (`knowledge_client.py`). Do not build a custom
   documentation search.
2. For the Events API itself: use the REST surface with a stored bearer token for the unattended
   worker (see ADR-001). Reserve the Events API's own MCP server for scenarios where a human is
   already present and signed in via their agent client (Kiro, Claude Code, etc.) — SessionMind's
   custom MCP server calls the *REST* client, not the official Events API MCP server, to avoid a
   double sign-in dependency.

## Consequences

**Positive:**
- Zero custom code needed to search AWS documentation — the official Knowledge server already
  does this well, is publicly reachable with no credentials, and is maintained by AWS.
- No token/auth management needed for the documentation lookup at all (it's unauthenticated).
- The unattended worker has a single, well-understood auth dependency (one Events API bearer
  token in Secrets Manager) instead of two different sign-in flows.

**Negative:**
- The worker's briefing quality depends on the Knowledge server's availability and relevance
  matching; `knowledge_client.search_documentation` swallows all errors and returns `[]` on
  failure, so an outage silently produces a briefing with a generic "no related docs found" line
  rather than blocking the whole run — a deliberate degrade-gracefully choice, but it means a
  Knowledge server outage is not loudly surfaced without checking logs.
- `search_documentation`'s topic-based relevance is only as good as the session's own `topics`
  taxonomy; sessions with a sparse taxonomy produce a broader, less targeted query.
