"""MCP server exposing retrieval as a `search_filings` tool.

Thin adapter over FilingSearch (search.py holds the logic). Runs over
streamable-http so any host — our orchestrator, Claude Desktop, an agent harness —
can call it over the network. Building retrieval *as* an MCP server is the pattern
this demonstrates; see docs/retrieval-and-serving.md.

Uses the mcp 2.x SDK, where FastMCP was renamed MCPServer.

Run: `uv run python -m financial_doc_ai.retrieval.server`
"""

import os

from mcp.server.mcpserver import MCPServer

from financial_doc_ai.query.rewriter import Filters
from financial_doc_ai.retrieval.search import FilingSearch

mcp = MCPServer("filings")

# One shared search core (real Embedder + VectorStore, both configured from env).
# Built once at import; the tool call stays a thin translation layer.
_search = FilingSearch()


@mcp.tool()
def search_filings(
    query: str,
    company: list[str] | None = None,
    doc_type: list[str] | None = None,
    period: list[str] | None = None,
    version: str = "current",
    top_k: int = 5,
) -> list[dict]:
    """Semantic search over indexed filings, filtered by document metadata.

    Filters must be already-resolved, canonical values matching the stamped
    corpus: `company` = ticker (e.g. "AAPL"), `doc_type` = form (e.g. "10-K"),
    `period` = fiscal year (e.g. "2024"), `version` = "current". Returns the most
    relevant passages, each with the citation metadata needed to attribute it.
    """
    filters = Filters(
        company=company, doc_type=doc_type, period=period, version=version
    )
    results = _search.search(query, filters, top_k=top_k)
    return [r.model_dump() for r in results]


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8001")),
    )
