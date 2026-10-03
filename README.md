# SessionMind AI — AWS re:Invent Event Catalog API Hackathon Submission

SessionMind AI is a context-aware briefing and trip-report agent for AWS conference attendees,
built on the real [AWS Events API](https://docs.aws.amazon.com/events/latest/devguide/what-is-events-api.html)
(`https://api.awsevents.com`) and the official [AWS Knowledge MCP server](https://github.com/awslabs/mcp/blob/main/src/aws-knowledge-mcp-server/README.md).
Submitted to the [re:Invent Event Catalog API Hackathon](https://builder.aws.com/build/hackathons/7c0e8c59-35d9-3ceb-8f80-0d5dc41bfebf/reinvent-event-catalog-api-hackathon).

See [`PROJECT_DESCRIPTION.md`](./PROJECT_DESCRIPTION.md) for the contest submission writeup (what
was built, why, and how it uses the API/MCP server), or jump straight into the code:

**[→ session-mind-ai/](./session-mind-ai)** — full source, tests, infrastructure, and docs.

## What it does, in short

- **Before a session**: pulls your reserved sessions, fetches real session metadata, queries the
  AWS Knowledge MCP server for grounding documentation, and generates a short prep card.
- **During/after a session**: lets you jot a note bound to that session (optionally with a
  recording link you found yourself).
- **At the end of the conference**: synthesizes your real notes and real session metadata into a
  Markdown trip report, a LinkedIn post draft, and an AWS Builder Center blog post draft — all
  from the same underlying real data, with editable placeholders left wherever your own voice is
  genuinely needed.

Everything is exposed both as REST-backed Lambda automation (for the unattended pre-session
worker) and as MCP tools (for interactive use through an agent like Kiro, Claude Code, or Amazon
Q Developer).

## Repo layout

```
AWS hackathon/
├── README.md                  <- you are here
├── PROJECT_DESCRIPTION.md     <- contest submission writeup
├── session-mind-ai/           <- the module: src/, tests/, infra/, docs/, scripts/
├── fixtures/                  <- real JSON captures from the live Events API (used in tests/docs)
└── tools/                     <- get_events_api_token.py, a standalone Builder-ID sign-in helper
```

## Verified against the real API

The AWS Events API's actual JSON shape differs in several concrete ways from how the devguide's
prose describes it. Rather than build against assumptions, every claim below was checked against
live traffic:

- **Confirmed live** (by calling real, public, no-registration-required catalogs such as AWS
  Summit events): `ListSessions` returns `{ items: [...], totalCount, nextToken? }` — the array
  key is `items`, not `sessions`. `GetSession` returns `{ session: {...} }`, wrapped. A real
  session has `abbreviation` (not `sessionCode`), `room` (no separate `venue` field), a compound
  `level` string (e.g. `"100 – Foundational"`, never a bare number), and `sessionTime: { date,
  time, length, timezone }` instead of ISO `start`/`end` fields. There is **no `tracks` field
  anywhere** — real taxonomy is `topics`/`areasOfInterest`/`industries`/`roles`/`services`. See
  `fixtures/` for the raw captures and `session-mind-ai/docs/hldd.md` for the full detail.
- **Devguide-only, not verified live**: `GetSchedule`, which requires a token for an attendee
  registered to a specific event. A real, valid, unexpired Builder ID token returned
  `403 Forbidden` ("not registered for this event") against both `reinvent2025` and
  `reinvent2026` — registration for the live event could not be confirmed from this environment.
  SessionMind's `GetSchedule`-dependent paths are tested against the devguide's documented shape
  and unit-tested with mocked responses, but not confirmed against a live response.

SessionMind ships a live, network-dependent smoke test (gated behind `RUN_LIVE_SMOKE_TESTS=1`,
skipped by default) that re-verifies the `ListSessions`/`GetSession` claims above on demand — see
`session-mind-ai/tests/test_live_smoke.py`.

## Recordable demos (no event registration required)

**Visual, in a browser:**
```powershell
cd session-mind-ai
python -m pip install -e ".[webapp]"
python -m uvicorn webapp.server:app --reload
```
Open http://127.0.0.1:8000. A FastAPI + vanilla-JS UI over the same real modules below — pick a
real public event, browse its real catalog, view a live prep card, build a schedule, capture
notes, and generate real trip-report/LinkedIn/Builder-Center drafts, all in the browser.

**Terminal:**
```powershell
cd session-mind-ai
python scripts/demo.py
```
The original walkthrough. Runs entirely against a real, public AWS Summit catalog — no mocks, no
registration. Real `GetSession` calls, a real AWS Knowledge MCP query, a real prep card, real
note capture, and real trip-report/LinkedIn/Builder-Center drafts, each written to
`session-mind-ai/scripts/output/`.

See [`session-mind-ai/README.md`](./session-mind-ai/README.md) for full setup, deployment, and
MCP configuration instructions.

## Getting a real bearer token (optional, for live `GetSchedule` testing only)

Not required to run tests or the demo — both work fully offline/against public catalogs. If you
want to test against your own reserved schedule on a registered event:

1. Register for the target event through its own registration site. A valid token from someone
   *not* registered for that event gets a 403, not a 401.
2. Run the included helper, which performs the OAuth 2.0 Authorization Code + PKCE flow locally
   and opens your browser to sign in with AWS Builder ID:
   ```powershell
   python tools/get_events_api_token.py
   ```
   It prints a ready-to-paste `$env:EVENTS_API_TOKEN = "..."` line, plus a refresh token valid for
   30 days (`python tools/get_events_api_token.py --refresh "<refresh_token>"`).
3. Set `$env:EVENTS_API_EVENT_ID` to the target event ID.

Treat both tokens as credentials — don't commit them or paste them into shared logs. The access
token expires in 60 minutes; the refresh token doesn't extend your underlying Builder ID session.
