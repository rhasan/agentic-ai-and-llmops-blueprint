from financial_doc_ai.company_resolver import CompanyResolver
from financial_doc_ai.pipeline import QueryPipeline
from financial_doc_ai.query_rewriter import Filters, QueryRewrite


class _StubRewriter:
    """Returns a fixed QueryRewrite so the pipeline needs no Phoenix/Ollama."""

    def __init__(self, rewrite: QueryRewrite) -> None:
        self._rewrite = rewrite

    def rewrite(self, question: str, session_context: str | None = None) -> QueryRewrite:
        return self._rewrite


def test_run_resolves_extracted_companies():
    rewrite = QueryRewrite(
        query_type="other",
        rewritten_query="What was Apple's net sales in 2024?",
        filters=Filters(company=["Apple"], period=["2024"]),
    )
    pipeline = QueryPipeline(rewriter=_StubRewriter(rewrite), resolver=CompanyResolver())

    result = pipeline.run("What was Apple net sales in 2024?")

    assert result.rewrite is rewrite
    assert [c.outcome for c in result.companies] == ["resolved"]
    assert result.companies[0].canonical.ticker == "AAPL"


def test_run_with_no_company_filter_resolves_nothing():
    rewrite = QueryRewrite(
        query_type="other",
        rewritten_query="What are the main risk factors?",
        filters=Filters(company=None),
    )
    pipeline = QueryPipeline(rewriter=_StubRewriter(rewrite), resolver=CompanyResolver())

    result = pipeline.run("What are the main risk factors?")

    assert result.companies == []
