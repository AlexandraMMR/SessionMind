"""Client for the official AWS Knowledge MCP server.

Public, unauthenticated, remote MCP server at https://knowledge-mcp.global.api.aws
(streamable HTTP transport). See
https://github.com/awslabs/mcp/blob/main/src/aws-knowledge-mcp-server/README.md

We connect to it as an MCP *client* (not wrap it in REST) since that's the
only surface it exposes; the `mcp` Python SDK's streamable-HTTP client
transport handles the session lifecycle for us.

`aws___search_documentation` is the one tool SessionMind needs: given the
session's topics/areas of interest, find grounding AWS documentation to
cite in the pre-session prep card. The real tool name carries an
`aws___` prefix -- confirmed live via `session.list_tools()` against the
real server on 2026-10-03 -- not the bare `search_documentation` name a
first reading of the README might suggest.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

KNOWLEDGE_MCP_URL = "https://knowledge-mcp.global.api.aws"


@asynccontextmanager
async def knowledge_session(url: str = KNOWLEDGE_MCP_URL) -> AsyncIterator[ClientSession]:
    async with streamablehttp_client(url) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def search_documentation(query: str, limit: int = 3) -> list[dict]:
    """Calls the `search_documentation` tool and normalizes results to
    a list of {"title": ..., "url": ..., "snippet": ...} dicts.

    Returns an empty list (rather than raising) on any transport/tool
    error, since a missing doc link should degrade the briefing quality,
    not fail it outright.
    """
    try:
        async with knowledge_session() as session:
            # The real tool name is prefixed `aws___search_documentation`,
            # confirmed live via `session.list_tools()` on 2026-10-03 --
            # not the bare `search_documentation` the README prose implies.
            result = await session.call_tool(
                "aws___search_documentation", {"search_phrase": query, "limit": limit}
            )
    except Exception:
        return []

    items: list[dict] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if not text:
            continue
        items.append({"title": query, "url": None, "snippet": text})
    return items[:limit]
