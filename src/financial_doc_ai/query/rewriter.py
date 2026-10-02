"""Retrieval filters — the structured constraints a search runs under.

`Filters` is shared: the vector search (`retrieval/search.py`, `retrieval/server.py`)
and the agent's confirm gate both key off it. It once carried a `QueryRewriter`
(question -> structured request) for the deterministic orchestrator path; that
path was removed in favour of the agent loop, which decomposes questions itself.
"""

from pydantic import BaseModel


class Filters(BaseModel):
    company: list[str] | None = None
    doc_type: list[str] | None = None
    period: list[str] | None = None
    version: str = "current"
