"""Online orchestrator: the two-call HITL flow that guards mis-extraction.

`interpret(question)` runs rewrite -> resolve and proposes filters, flagging when
the analyst must confirm before retrieval. `answer(question, confirmed_filters)`
takes the (possibly corrected) filters back and calls the `search_filings` MCP
tool. Splitting the two puts a human confirmation gate in front of retrieval — the
one failure the grounding check can't catch (answer correctly grounded in the
*wrong* document). See docs/retrieval-and-serving.md.

Generation + grounding + audit come later; `answer` currently stops at retrieved,
cited passages — enough to exercise the gate end-to-end.
"""

from pydantic import BaseModel

from financial_doc_ai.query.pipeline import QueryPipeline, ResolvedQuery
from financial_doc_ai.query.resolver import Resolution
from financial_doc_ai.query.rewriter import Filters
from financial_doc_ai.retrieval.search import SearchResult
from financial_doc_ai.serving.search_client import SearchClient


class Interpretation(BaseModel):
    query_type: str
    rewritten_query: str
    proposed_filters: Filters
    companies: list[Resolution]
    needs_confirmation: bool
    reasons: list[str]


class Answer(BaseModel):
    results: list[SearchResult]


def _needs_confirmation(resolved: ResolvedQuery) -> tuple[bool, list[str]]:
    """Filters are always surfaced; this decides when to *force* a confirm.

    Weak signals: a company that didn't resolve cleanly, or a multi-company
    comparison (both are prime mis-extraction spots). Returns the reasons so the
    client can tell the analyst why.
    """
    reasons: list[str] = []
    for res in resolved.companies:
        if res.outcome == "not_found":
            reasons.append(f"Could not resolve company '{res.input}'.")
        elif res.outcome == "ambiguous":
            reasons.append(f"Company '{res.input}' is ambiguous.")

    resolved_count = sum(1 for r in resolved.companies if r.outcome == "resolved")
    if resolved.rewrite.query_type == "compare" and resolved_count > 1:
        reasons.append("Multi-company comparison — confirm the companies to compare.")

    return (len(reasons) > 0, reasons)


class Orchestrator:
    def __init__(
        self,
        pipeline: QueryPipeline | None = None,
        search_client: SearchClient | None = None,
    ) -> None:
        self.pipeline = pipeline if pipeline is not None else QueryPipeline()
        # Left None until first use so `interpret` (which never retrieves) doesn't
        # require SEARCH_MCP_URL; the default client is built lazily in `answer`.
        self.search_client = search_client

    def interpret(self, question: str, session_context: str | None = None) -> Interpretation:
        resolved = self.pipeline.run(question, session_context)
        needs, reasons = _needs_confirmation(resolved)
        # Show canonical tickers in the proposed filters — the corpus is stamped
        # with tickers (company=AAPL), so retrieval needs the resolved value, not
        # the surface form the analyst typed. Unresolved inputs keep the surface
        # form (needs_confirmation is already True) so the analyst sees what to fix.
        companies = [
            r.canonical.ticker if r.outcome == "resolved" and r.canonical else r.input
            for r in resolved.companies
        ]
        proposed = resolved.rewrite.filters.model_copy(
            update={"company": companies or None}
        )
        return Interpretation(
            query_type=resolved.rewrite.query_type,
            rewritten_query=resolved.rewrite.rewritten_query,
            proposed_filters=proposed,
            companies=resolved.companies,
            needs_confirmation=needs,
            reasons=reasons,
        )

    async def answer(
        self, question: str, confirmed_filters: Filters, top_k: int = 5
    ) -> Answer:
        # Retrieve on the CONFIRMED filters — no re-run of rewrite/resolve. That
        # the human-corrected filters drive retrieval is the point of the gate.
        if self.search_client is None:
            self.search_client = SearchClient()
        results = await self.search_client.search(question, confirmed_filters, top_k)
        return Answer(results=results)
