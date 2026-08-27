"""Online query path composition (early stage).

Runs query rewrite, then resolves the extracted company surface forms to canonical
tickers. The two stages stay separate (rewrite is LLM-only, the resolver is
deterministic); this module is where they are composed. Extends into the full
retrieve -> generate -> grounding -> audit path later.
"""

from pydantic import BaseModel

from financial_doc_ai.query.resolver import CompanyResolver, Resolution
from financial_doc_ai.query.rewriter import QueryRewrite, QueryRewriter


class ResolvedQuery(BaseModel):
    rewrite: QueryRewrite
    companies: list[Resolution]


class QueryPipeline:
    def __init__(
        self,
        rewriter: QueryRewriter | None = None,
        resolver: CompanyResolver | None = None,
    ) -> None:
        self.rewriter = rewriter if rewriter is not None else QueryRewriter()
        self.resolver = resolver if resolver is not None else CompanyResolver()

    def run(self, question: str, session_context: str | None = None) -> ResolvedQuery:
        rewrite = self.rewriter.rewrite(question, session_context)
        companies = self.resolver.resolve(rewrite.filters.company or [])
        return ResolvedQuery(rewrite=rewrite, companies=companies)
