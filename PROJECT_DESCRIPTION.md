# SessionMind Project Description

*Submission for the AWS re:Invent Event Catalog API Hackathon*

## What I built

SessionMind is a context-aware assistant for AWS event or conference attendees that closes the loop on three moments every attendee hits and usually handles badly: showing up to a session forgetting what it was about from registering 2 months ago, losing track of what you actually learned, and never getting around to writing up or sharing notes afterward.

Concretely, it does three things:

1. **Pre-session briefings.** On a schedule (every 15 minutes via EventBridge), it checks your
   reserved sessions, and for anything starting soon it pulls the real session abstract and
   taxonomy, queries the official AWS Knowledge MCP server for grounding documentation on the
   topic, and produces a short 3-bullet prep card — what the session covers, what concepts to
   skim beforehand, and a related doc to read first.
2. **In-session note capture.** A single MCP tool call binds a free-text note to a specific real
   session ID, optionally with a recording link you found yourself (never auto-matched — more on
   why below).
3. **Post-conference synthesis.** On request, it aggregates every note you took with the official
   metadata for every session you reserved and produces a Markdown trip report, a LinkedIn post
   draft, and an AWS Builder Center blog post draft — all from the same real underlying data, with
   your voice left as an editable placeholder wherever a personal opinion or outcome is genuinely
   required.

## Why I built it

Two real, unglamorous problems show up at every multi-track conference:

- **You forget the context you needed by the time the session starts.** You reserved a session
  weeks ago; by the time it starts you've forgotten what it's about or what you were hoping to
  get from it. A short, automatically-delivered reminder with the actual abstract and a related
  doc link solves this without requiring you to re-read your own agenda.
- **Writing up a trip report is tedious enough that most people skip it, and skip the social
  post that would come from it.** The information to write a good trip report already exists —
  it's just scattered across your own notes and the conference catalog. Nobody wants to
  re-type session titles and abstracts by hand to draft a LinkedIn post afterward, so most people
  either don't bother or write something generic. If the system already has your notes and the
  real session metadata, drafting the first version of that write-up is a mechanical aggregation
  step, not a creative one — the creative part (your actual opinion, your actual takeaway) is the
  one piece a system has no business inventing, so that's exactly what's left as a placeholder.

I built it specifically against the **real** AWS Events API rather than an idealized version of
it, because the first thing I learned building this is that the devguide's prose description and
the live JSON response diverge in several concrete ways (see "How it uses the API" below).

## How it uses the AWS Events API and the MCP server

**REST API** (`https://api.awsevents.com/v1`), used for the unattended briefing worker because the
official MCP server requires an interactive browser sign-in on every single call, which is
incompatible with an EventBridge-triggered Lambda running with nobody watching:
- `GetSchedule` — the attendee's reserved sessions.
- `GetSession` / `ListSessions` — real session metadata (abstract, taxonomy, timing, speakers).

**Official AWS Knowledge MCP server** (`https://knowledge-mcp.global.api.aws`, public,
unauthenticated), connected to directly as an MCP client rather than reimplemented: its
`search_documentation` tool grounds each prep card in real, current AWS documentation relevant to
the session's topics.

**A custom MCP server** (this project's own value-add, not part of the official API) exposes seven
tools for interactive use through an agent client (Kiro, Claude Code, Amazon Q Developer):
`get_user_schedule`, `get_session_details`, `build_session_prep_card`, `record_session_note`,
`generate_trip_report`, `generate_linkedin_draft`, and `generate_builder_center_draft`. Each of
the last three is template-based and deterministic — no LLM call — which keeps the entire
retrieval pipeline (fetch real sessions, fetch real notes, assemble) unit-testable without AWS
credentials, while leaving a documented seam for a future Bedrock-backed generation pass over the
same real, retrieved context.

**What I verified live, not just assumed:** the AWS Events API's actual JSON shape differs from
how the devguide's prose describes it in several concrete ways I only found by calling real,
public (no-registration) event catalogs and inspecting the raw response — `ListSessions` returns
its array under `items`, not `sessions`; `GetSession` wraps its result in a `session` key; there
is no `tracks` field anywhere in the real catalog (real taxonomy is
`topics`/`areasOfInterest`/`industries`/`roles`/`services`); session timing comes as a
`{date, time, length, timezone}` object, not ISO `start`/`end` strings. All of this is captured in
real JSON fixtures in the repo and covered by a live, network-dependent smoke test that
re-verifies these claims against live traffic on demand. `GetSchedule`, which requires a token for
an attendee registered to a specific event, remains unverified against live data in this
environment — every attempt with a real, valid, unexpired Builder ID token returned
`403 Forbidden` ("not registered for this event") for the events reachable here, so that code
path is tested against the devguide's documented shape with mocked responses, not a live
response, and the project's own docs say so plainly rather than treating it as equally confirmed.

## Try it

Two ways to see it running against the real API with no setup beyond cloning the repo:

- **Visual, in a browser**: `cd session-mind-ai && python -m pip install -e ".[webapp]" && python -m uvicorn webapp.server:app --reload`, then open `http://127.0.0.1:8000`. A small FastAPI + vanilla-JS UI over the exact same real modules described above — pick a real public event, browse its real catalog, pull a live prep card, build a schedule, capture notes, and generate real trip-report/LinkedIn/Builder-Center drafts.
- **Terminal**: `cd session-mind-ai && python scripts/demo.py`.

Both talk only to real, public (no-registration) AWS event catalogs, so neither needs a Builder ID
token to run.

## What's deliberately not automated

The system never invents a personal opinion, a quantified outcome, or a session recording link on
your behalf. Recording links are attendee-supplied only, since the Events API has no
recording-URL field at all and most conference talks are never individually posted online —
auto-matching a session title to a video would risk silently attaching the wrong talk to the
wrong session, which is worse than attaching nothing in a report whose entire value is accuracy.
The same principle shapes the social drafts: hashtags and session highlights come only from real
catalog taxonomy and your own note text; anywhere your actual voice is required, the draft leaves
a bracketed placeholder instead of guessing.
