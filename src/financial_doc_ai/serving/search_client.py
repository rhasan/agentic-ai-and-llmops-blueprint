"""MCP client edge: calls the `search_filings` tool over streamable-http.

The orchestrator's only outbound dependency on the retrieval server. Kept thin and
injectable so the orchestrator's gate/wiring can be tested with a fake client and
the real transport is exercised by the in-container smoke. Stateless: a fresh MCP
session per call (no throughput concern at this scale; matches the stateless design).

mcp 2.x API notes: `streamable_http_client` yields a 2-tuple (read, write); the
tool's return lands in `CallToolResult.structured_content`, with a list result
wrapped as {"result": [...]}.
"""

import os

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from financial_doc_ai.query.rewriter import Filters
from financial_doc_ai.retrieval.search import SearchResult


class SearchClient:
    def __init__(self, url: str | None = None) -> None:
        # e.g. http://retrieval-app-1:8001/mcp — fail loudly if unset.
        self.url = url or os.environ["SEARCH_MCP_URL"]

    async def search(
        self, query: str, filters: Filters, top_k: int = 5
    ) -> list[SearchResult]:
        # Filters' fields line up 1:1 with the tool params, so the spread just
        # works; version is always sent (matches the stamped corpus default).
        arguments = {"query": query, "top_k": top_k, **filters.model_dump()}
        async with (
            streamable_http_client(self.url) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool("search_filings", arguments)
        data = result.structured_content
        rows = data["result"] if isinstance(data, dict) and "result" in data else data
        return [SearchResult(**row) for row in rows]
