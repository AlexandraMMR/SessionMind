# SessionMind AI, Product Requirements Document

## 1. Objective & target audience

**Objective:** Maximize educational value and technical retention by generating automated
pre-session technical context briefings and synthesizing post-conference executive summary trip
reports.

**Target audience:** Developers, cloud architects, and enterprise executives who need to document
learnings and present trip reports to stakeholders.

## 2. Key user stories

- As an attendee, I want a short briefing shortly before a session starts, containing the
  session's context and related documentation links, so I'm prepared going in.
- As an attendee, I want to record raw text notes during a talk and have them bound automatically
  to the specific session's metadata.
- As an enterprise team lead, I want an agent to aggregate all notes from my attended sessions
  and generate a structured Markdown executive report.

## 3. Success metrics (KPIs)

- **Pre-session briefing coverage:** 100% of reserved sessions starting within the lookahead
  window receive a prep card during the worker's run.
- **Synthesis latency:** trip report generation completes in a few seconds for a typical
  attendee's reserved-session count (dominated by sequential `GetSession` calls, see HLDD).

## 4. Correction vs. the original concept

The original draft assumed tools named `get_user_schedule`, `get_session_details`,
`get_speaker_profile`, and `aws_knowledge_search`. The real AWS Events API has **no**
`get_speaker_profile` operation. A session's `speakers` field is just a list of names, with no
dedicated speaker-profile endpoint. It also does not expose "prerequisite" fields directly; we
derive prep-card content from `topics`/`tracks`/`abstract` instead. The AWS Knowledge MCP server
is a distinct, already-existing public server (`https://knowledge-mcp.global.api.aws`) with its
own `search_documentation` tool. We call it directly rather than re-implementing it.

## 5. Scope

**In scope:**
- Periodic (15-minute) EventBridge-triggered worker that finds reservations starting soon,
  fetches session details, queries the AWS Knowledge MCP server for grounding docs, and publishes
  a 3-bullet prep card to SNS.
- Attendee note capture bound to a `sessionId`, via an MCP tool (`record_session_note`), stored
  either in-memory (local/dev) or Amazon OpenSearch Serverless (deployed).
- `generate_trip_report`: aggregates notes + official session metadata into a Markdown executive
  summary, sorted so sessions with notes surface first.

**Out of scope:**
- Actual push/mobile notification delivery beyond publishing to SNS. A subscriber such as email,
  SMS, or mobile push via a further integration is left to the deployer.
- PDF rendering (Markdown is produced; PDF conversion is a presentation-layer concern outside this
  module's scope).
- A hosted, multi-tenant notes database with per-user isolation. The reference implementation
  uses one collection; a production multi-attendee deployment would need per-attendee
  partitioning, which is flagged, not built, here.
