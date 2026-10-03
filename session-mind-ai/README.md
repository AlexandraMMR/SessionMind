# SessionMind AI

Context-aware pre-session briefing & post-conference trip-report agent for AWS re:Invent, built on
the AWS Events API and the official AWS Knowledge MCP server.

Docs: [PRD](docs/prd.md) · [HLDD](docs/hldd.md) · [ADR-001 (MCP-primary for interactive use)](docs/adr/ADR-001-mcp-primary-for-interactive-use.md) · [ADR-002 (Knowledge MCP + REST split)](docs/adr/ADR-002-mcp-sign-in-forces-rest-for-worker.md)

## What it does

- Every 15 minutes, finds reservations starting soon, pulls session details, queries the AWS
  Knowledge MCP server for grounding docs, and publishes a 3-bullet prep card to SNS.
- Lets an attendee record a note bound to a `sessionId` via an MCP tool.
- Generates a Markdown trip report aggregating notes with official session metadata, on request.
- Drafts a LinkedIn post and an AWS Builder Center blog post from the same real sessions + notes
  (`generate_linkedin_draft` / `generate_builder_center_draft`), with editable placeholders left
  wherever the attendee's own voice is required. Never a fabricated opinion or outcome metric.
- Ships a small visual browser demo (`webapp/`) and a terminal demo (`scripts/demo.py`), both
  driving the exact same real logic above against a live, public AWS event catalog.

## Layout

```
src/session_mind_ai/
  events_api_client.py   AWS Events API REST client (ListEvents, GetSchedule, GetSession, ListSessions)
  knowledge_client.py     MCP client for the official AWS Knowledge server
  briefing.py             Deterministic prep-card builder
  notes_store.py          NotesStore protocol + in-memory and OpenSearch Serverless implementations
  trip_report.py          Note aggregation + Markdown rendering
  social_drafts.py         LinkedIn + Builder Center blog draft generation (same data as trip_report)
  briefing_worker.py       Lambda handler (EventBridge-triggered)
  mcp_server.py            Companion MCP server for interactive agent use
webapp/                   FastAPI + vanilla-JS visual demo (same real modules, browser UI on top)
  server.py                 Endpoints wrapping events_api_client/briefing/trip_report/social_drafts
  static/                   index.html, styles.css, app.js
scripts/
  demo.py                  Terminal demo (see "CLI demo" below)
infra/                    AWS CDK (Python) stack
tests/                    pytest unit tests (including tests/test_webapp.py)
docs/                     PRD, HLDD, ADRs
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

## Visual demo (browser, no registration required)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[webapp]"
.\.venv\Scripts\python.exe -m uvicorn webapp.server:app --reload
```

Then open **http://127.0.0.1:8000**. This is a small FastAPI and vanilla JS single-page app that
drives the exact same real modules as everything else in this repo (`events_api_client`,
`briefing`, `trip_report`, `social_drafts`). Nothing in `webapp/` reimplements or mocks the
underlying logic; it's a UI on top of it, built so the demo is recordable as a browser
walkthrough instead of scrolling terminal output:

1. Pick a real, public AWS event (real `ListEvents`, filtered to events that don't require
   registration).
2. Browse its real session catalog (real `ListSessions`) and view a prep card for any session
   (real `GetSession` + a live AWS Knowledge MCP lookup).
3. Add real sessions to "My Schedule", a manual stand-in for `GetSchedule`, since a public event
   has no schedule to pull in the first place (same constraint as the CLI demo, see below).
4. Capture notes bound to real session IDs, optionally with a recording link you supply yourself.
5. Generate a trip report, LinkedIn draft, and Builder Center draft from that same real data.

Per-browser state (selected event, schedule, notes) lives server-side in memory, keyed by a
cookie. Restarting the server clears it, and it's not meant for multi-machine use; see
`webapp/server.py`'s module docstring for the full design rationale.

## CLI demo (terminal, no registration required)

```powershell
.\.venv\Scripts\python.exe scripts\demo.py
```

The original terminal walkthrough, still available. Runs against a REAL, public catalog
(`Summit-Toronto-2025` by default; pass another event ID as an argument): real `GetSession` calls,
a real query to the AWS Knowledge MCP server for grounding docs, real prep-card generation, real
note capture, a real Markdown trip report, and a real LinkedIn and Builder Center draft, all over
the notes just recorded, each written to a timestamped `.md` file under `scripts/output/`
(gitignored) in addition to printing it.

Both demos share the same constraint: SessionMind's tools never call
`GetSchedule`/`CreatePersonalTime`, only `ListSessions`/`GetSession` (both public).

## Running against the real API

Tests run fully offline (httpx `MockTransport`, in-memory notes store). For live use:

```powershell
$env:EVENTS_API_TOKEN = "<bearer token from AWS Builder ID OAuth flow>"
$env:EVENTS_API_EVENT_ID = "reinvent2026"
```

Run the MCP server directly:

```powershell
.\.venv\Scripts\python.exe -m session_mind_ai.mcp_server
```

Or add it to an MCP client config:

```json
{
  "mcpServers": {
    "session-mind": {
      "command": "<path-to-venv>/Scripts/python.exe",
      "args": ["-m", "session_mind_ai.mcp_server"],
      "env": { "EVENTS_API_TOKEN": "...", "EVENTS_API_EVENT_ID": "reinvent2026" }
    }
  }
}
```

## Deploying

Requires the AWS CDK CLI and a Python virtualenv with `infra/requirements.txt` installed:

```powershell
cd infra
..\.venv\Scripts\Activate.ps1   # use the module's venv so `python app.py` resolves correctly
pip install -r requirements.txt
cdk bootstrap   # first time per account/region
cdk deploy
```

This deploys an SNS topic for briefing cards, an EventBridge-triggered Lambda worker (bundled with
the `session_mind_ai` package via a Lambda-compatible `pip install` at synth time), and an Amazon
OpenSearch Serverless collection with encryption/network/data-access policies for note storage.

## Future iteration ideas

- **Bedrock-backed drafting.** `build_linkedin_draft`/`build_builder_center_draft` are
  deterministic and template-based today, by design: no LLM call, fully unit-testable without
  AWS credentials. A natural next step is an optional pass through Amazon Bedrock that takes the
  same real inputs (session abstracts, taxonomy, and the attendee's own notes) and rewrites them
  into more natural prose, while still never inventing an opinion, outcome metric, or recording
  link the attendee didn't provide. This would sit alongside the current template output rather
  than replace it, so the deterministic version stays available as a fallback and for tests.

## Security notes

- The Secrets Manager secret (`session-mind-ai/events-api-token`) must be populated manually after
  completing the Builder ID OAuth flow. It is created empty by the stack.
- `OpenSearchNotesStore` currently grants the briefing worker's role broad `aoss:APIAccessAll` on
  the collection; this should be scoped down to the specific index actions actually needed before
  any production use.
- No authentication/authorization is implemented on who can call `record_session_note` or
  `generate_trip_report` via the MCP server; it is designed for single-attendee local use. A
  multi-tenant deployment needs per-attendee identity and data isolation, which is explicitly out
  of scope (see PRD).
