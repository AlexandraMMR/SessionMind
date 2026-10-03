# ADR-001 — MCP as the primary interactive surface, REST for the unattended worker

**Status:** Accepted

## Context

SessionMind has two very different usage modes: (1) an unattended, scheduled background job that
must run without a human approving a sign-in prompt, and (2) an inherently conversational
experience — asking for a briefing, jotting a note, requesting a trip report — that maps
naturally onto an agent's tool-calling loop. The AWS Events API's MCP server requires an
interactive OAuth sign-in on every call, which is fine for mode (2) but disqualifies it for mode
(1).

## Decision

Split the implementation along that boundary instead of picking one surface for the whole module:

- The periodic briefing worker (`briefing_worker.py`, Lambda + EventBridge) uses the **REST**
  client (`events_api_client.py`) with a stored bearer token, because it must run unattended.
- Everything else — fetching schedule/session details on demand, recording notes, generating a
  trip report — is exposed as a **custom MCP server** (`mcp_server.py`) for use by an interactive
  agent client. That server itself uses the same REST client under the hood; it does not
  reimplement Events API auth or proxy the official MCP server.

## Consequences

**Positive:**
- The unattended path never blocks on a browser prompt.
- The interactive path gets a natural tool-calling interface matching how a user would actually
  ask for a briefing or a trip report ("summarize my re:Invent week").
- A single REST client implementation is shared by both paths — no duplicated Events API logic.

**Negative:**
- Two runtime entry points (Lambda handler, MCP stdio server) means two things to keep in sync
  when the Events API's schema changes, though both depend on the same `events_api_client.py`
  module so a breaking API change only needs one code fix.
- The MCP server's `record_session_note`/notes storage is process-lifetime in-memory by default
  (see `notes_store.py`); a deployed, persistent variant needs to be wired to
  `OpenSearchNotesStore` explicitly rather than getting it "for free" from using the MCP server.
