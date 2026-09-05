"""MCP server exposing graph retrieval as a `graph_search` tool.

Thin adapter over GraphSearch (search.py holds the logic), mirroring the vector
retrieval server. Its own service keeps the heavy graphrag/LanceDB deps out of the
serving container and makes the two retrieval sources symmetric — both reachable
over streamable-http by any host on llm-net. See
docs/specs/graphrag-financial-doc-ai.md.

Uses the mcp 2.x SDK, where FastMCP was renamed MCPServer.

Run: `uv run python -m financial_doc_ai.graph_retrieval.server`
"""

import os

from mcp.server.mcpserver import MCPServer

from financial_doc_ai.graph_retrieval.search import GraphSearch

mcp = MCPServer("graph")

# One shared search core, built once at import (loads the index parquets +
# configures models from env); the tool call stays a thin translation layer.
_search = GraphSearch()


@mcp.tool()
async def graph_search(query: str, top_k: int = 10) -> dict:
    """Graph-based retrieval for cross-document and multi-hop questions.

    Runs a DRIFT search over the knowledge graph built from the filings —
    following relationships across documents rather than matching a single
    passage — and returns a synthesized sub-answer plus the supporting passages
    (each with citation metadata). Prefer this over passage search when the
    question spans multiple documents or needs entities/relationships connected.
    Unlike `search_filings` it is not filtered by document metadata.
    """
    result = await _search.search(query, top_k=top_k)
    return {
        "sub_answer": result.sub_answer.model_dump(),
        "results": [r.model_dump() for r in result.results],
    }


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8002")),
    )
