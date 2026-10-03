# SessionMind AI, High-Level Design Document

## API reality check

### Verified live (ListSessions / GetSession), as of 2026-10-03

Confirmed by calling the real, public (no-auth) catalogs of several AWS Summit events
(`Summit-Toronto-2025` and others) and inspecting the raw JSON, not just paraphrasing the
devguide. The real shape differs meaningfully from this module's first draft:

- `ListSessions` returns `{ items: [...], totalCount, nextToken? }`. The array key is
  **`items`**, not `sessions`.
- `GetSession` returns `{ session: {...} }`, wrapped, not flat.
- A real session has: `sessionId`, `title`, `abstract?`, `abbreviation?` (not `sessionCode`; that
  field does not exist), `type?`, `level?` (a compound string like `"100 – Foundational"`, the
  API's own literal value, never a bare number), `isAllDaySession`, `room?` (no separate `venue`
  field), `sessionTime?: { date, time, length, timezone }` (no `start`/`end` ISO field at all,
  synthesized by
  `events_api_client._derive_session_times`, naive-local arithmetic, not real timezone-aware
  math), `speakers?: [{ name: "Person, Org" }]` (combined strings in dict wrappers, not bare
  strings), and taxonomy as `topics?`, `areas_of_interest?`, `industries?`, `roles?`, `services?`.
  **There is no `tracks` field anywhere**; corrected in `events_api_client.Session`.
- `events_api_client.upcoming_reservations` only reads `GetSchedule`'s `reservations`. A
  favorite is interest, not a commitment to brief (see "devguide-only" caveat below for
  `GetSchedule` itself).
- `briefing.py` degrades gracefully on missing fields (e.g. "No abstract published yet.") rather
  than erroring, since real sessions routinely omit several of the optional fields above.
- `tests/test_events_api_client.py` is built against a real captured fixture; see also
  `fixtures/list_sessions_sample.json` and `fixtures/get_session_sample.json` at the repo root.
  `tests/test_live_smoke.py` (gated behind `RUN_LIVE_SMOKE_TESTS=1`) re-verifies this against live
  traffic on demand.

### Devguide-only, NOT verified live (GetSchedule)

`GetSchedule` requires a token for an attendee registered to a specific event. Every event this
project's test token could reach (`reinvent2025`, `reinvent2026`) returned `403 Forbidden`. This
was a valid, unexpired token, correctly rejected as "not registered for this event" (confirmed by
decoding the JWT and by the documented 401 vs. 403 distinction). **No real `GetSchedule` response
has been observed.** The `reservations`/`favorites`/`personalTime` array shape and the
`sessionId`/`startDateTime`/`endDateTime` field names on schedule entries are still based on the
devguide's prose description only. Given how far the real `ListSessions`/`GetSession` shape
diverged from the devguide's prose, treat this as a credible best guess, not a confirmed fact.

- The **AWS Knowledge MCP server** (`https://knowledge-mcp.global.api.aws`, public, no auth) is a
  separate, pre-existing AWS service, not something we built. We connect to it as an MCP client
  (`knowledge_client.py`). **Verified live**: the real tool name is `aws___search_documentation`
  (the `aws___` prefix, confirmed via `session.list_tools()`), not the bare `search_documentation`
  name a first reading of its own README might suggest. Confirmed by both `scripts/demo.py` and
  the `webapp/` demo successfully returning real doc snippets against live traffic.

## System architecture and data flow

SessionMind is MCP-primary for interactive use. It is inherently a conversational agent
surface; briefings and trip reports are naturally requested and consumed through an agent. It is
REST-backed for its one piece of unattended automation, the periodic briefing worker. See
ADR-002 for why MCP's per-call sign-in requirement rules it out for that worker.

```
Pre-session phase (unattended):
1. EventBridge (rate: 15 min)
        │
        ▼
2. briefing_worker.handler (Lambda)
        │  GetSchedule → filter reservations starting in [15, 20) min
        ▼
3. GetSession (per upcoming reservation)
        │
        ▼
4. AWS Knowledge MCP server .search_documentation(topics)   [best effort, errors swallowed]
        │
        ▼
5. briefing.build_prep_card()  → 3-bullet card
        │
        ▼
6. SNS publish (BriefingTopic)  → downstream delivery (push/email/SMS) is the deployer's choice

Post-session phase (interactive, via our custom MCP server):
7. Agent ──stdio MCP──▶ session-mind-ai MCP server
        ├─ get_user_schedule        → GetSchedule
        ├─ get_session_details      → GetSession
        ├─ build_session_prep_card  → GetSession + build_prep_card (on-demand, not just on schedule)
        ├─ record_session_note      → NotesStore.add_note (sessionId-bound)
        └─ generate_trip_report     → GetSchedule + GetSession(*) + NotesStore + render_markdown
```

## Component responsibilities

| Component | File | Responsibility |
|---|---|---|
| REST client | `src/session_mind_ai/events_api_client.py` | Typed wrapper for `ListEvents`, `GetSchedule`, `GetSession`, paginated `ListSessions` |
| Knowledge client | `src/session_mind_ai/knowledge_client.py` | MCP client to the official AWS Knowledge server's `aws___search_documentation` |
| Briefing | `src/session_mind_ai/briefing.py` | Deterministic 3-bullet prep-card template from session metadata + doc snippets |
| Notes store | `src/session_mind_ai/notes_store.py` | `NotesStore` protocol; `InMemoryNotesStore` (tests/dev) and `OpenSearchNotesStore` (deployed) |
| Trip report | `src/session_mind_ai/trip_report.py` | Groups notes by session, sorts notes-first, renders Markdown |
| Social drafts | `src/session_mind_ai/social_drafts.py` | LinkedIn + Builder Center blog draft generation from the same `TripReportSection` data |
| Briefing worker | `src/session_mind_ai/briefing_worker.py` | Lambda handler: the "pre-session phase" pipeline above |
| MCP server | `src/session_mind_ai/mcp_server.py` | 7 tools for interactive agent use (schedule/session reads, prep card, notes, trip report, 2 social drafts) |
| Web demo | `webapp/server.py` + `webapp/static/` | FastAPI + vanilla-JS browser UI over the same modules above, for a recordable visual walkthrough; per-browser state kept server-side in memory, keyed by cookie |
| CLI demo | `scripts/demo.py` | Terminal walkthrough of the same real modules |
| CDK stack | `infra/session_mind_stack.py` | SNS topic, EventBridge rule + Lambda, OpenSearch Serverless collection + access/network/encryption policies, Secrets Manager token placeholder |

## Why the briefing/trip-report generation is template-based, not an LLM call

Both `briefing.build_prep_card` and `trip_report.render_markdown` are deterministic string
templates, not Bedrock invocations. This keeps the "retrieval" half of the RAG pipeline (fetching
the right session metadata + doc snippets + notes) fully unit-testable without AWS credentials or
model access. The "generation" half, an actual Bedrock AgentCore call that takes this same
retrieved context and produces more natural prose, is a documented extension point
(`briefing.py`'s module docstring references `render_with_bedrock` as the integration seam) rather
than something faked with hardcoded model output.

## API surface mapping

| Endpoint / tool | Surface | Functionality |
|---|---|---|
| `GET /events` | Official REST | `ListEvents`, no auth; used by the web demo to list real, public events to browse |
| `GET /events/{eventId}/schedule` | Official REST | Fetches reservations for the briefing worker and MCP tools |
| `GET /events/{eventId}/sessions` | Official REST | `ListSessions`, paginated; the catalog browsed in the web/CLI demos |
| `GET /events/{eventId}/sessions/{sessionId}` | Official REST | Deep session metadata for briefings/trip reports |
| `aws___search_documentation` | Official AWS Knowledge MCP tool | Grounding documentation for prep cards |
| `get_user_schedule` | Custom MCP tool (ours) | Thin wrapper over `GetSchedule` |
| `get_session_details` | Custom MCP tool (ours) | Thin wrapper over `GetSession` |
| `build_session_prep_card` | Custom MCP tool (ours) | On-demand prep card for any session, not just upcoming ones |
| `record_session_note` | Custom MCP tool (ours) | Writes to the `NotesStore` |
| `generate_trip_report` | Custom MCP tool (ours) | Full RAG-style synthesis over notes + session metadata |
| `generate_linkedin_draft` | Custom MCP tool (ours) | LinkedIn post draft over the same notes + session metadata |
| `generate_builder_center_draft` | Custom MCP tool (ours) | Builder Center blog post draft over the same notes + session metadata |

The web demo (`webapp/server.py`) exposes equivalent functionality as plain REST endpoints
(`/api/events`, `/api/sessions`, `/api/sessions/{id}/prep-card`, `/api/notes`,
`/api/reports/{trip-report,linkedin,builder-center}`) rather than MCP tools, since a browser
can't speak MCP directly. Every one of them calls the same underlying functions listed in
"Component responsibilities" above.
