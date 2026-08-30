"""Orchestrator gate policy + wiring.

Pure/hermetic: the gate policy is a pure function over a constructed ResolvedQuery,
and `answer` is driven with a fake async SearchClient (asyncio.run, no plugin). The
real MCP round-trip is covered by the in-container smoke, not here.
"""

import asyncio

from financial_doc_ai.query.pipeline import ResolvedQuery
from financial_doc_ai.query.resolver import Canonical, Resolution
from financial_doc_ai.query.rewriter import Filters, QueryRewrite
from financial_doc_ai.retrieval.search import Citation, SearchResult
from financial_doc_ai.serving.generator import GeneratedAnswer
from financial_doc_ai.serving.orchestrator import Orchestrator, _needs_confirmation

_AAPL = Canonical(ticker="AAPL", name="Apple Inc.", cik="320193")
_MSFT = Canonical(ticker="MSFT", name="Microsoft Corp.", cik="789019")


def _resolved(query_type="other", companies=None, filters=None) -> ResolvedQuery:
    return ResolvedQuery(
        rewrite=QueryRewrite(
            query_type=query_type,
            rewritten_query="q",
            filters=filters or Filters(),
        ),
        companies=companies or [],
    )


def _res(inp, outcome, canonical=None):
    return Resolution(input=inp, outcome=outcome, canonical=canonical, match_type="exact" if canonical else None)


# --- gate policy ---------------------------------------------------------------

def test_all_resolved_needs_no_confirmation():
    resolved = _resolved(companies=[_res("Apple", "resolved", _AAPL)])
    needs, reasons = _needs_confirmation(resolved)
    assert needs is False
    assert reasons == []


def test_not_found_forces_confirmation():
    resolved = _resolved(companies=[_res("Acme", "not_found")])
    needs, reasons = _needs_confirmation(resolved)
    assert needs is True
    assert any("Acme" in r for r in reasons)


def test_ambiguous_forces_confirmation():
    resolved = _resolved(companies=[_res("Delta", "ambiguous")])
    needs, reasons = _needs_confirmation(resolved)
    assert needs is True
    assert any("ambiguous" in r.lower() for r in reasons)


def test_multi_company_compare_forces_confirmation():
    resolved = _resolved(
        query_type="compare",
        companies=[_res("Apple", "resolved", _AAPL), _res("Microsoft", "resolved", _MSFT)],
    )
    needs, reasons = _needs_confirmation(resolved)
    assert needs is True
    assert any("comparison" in r.lower() for r in reasons)


def test_single_company_compare_does_not_force():
    # "compare" with only one resolved company isn't a multi-company comparison.
    resolved = _resolved(query_type="compare", companies=[_res("Apple", "resolved", _AAPL)])
    needs, _ = _needs_confirmation(resolved)
    assert needs is False


# --- interpret wiring ----------------------------------------------------------

class _StubPipeline:
    def __init__(self, resolved: ResolvedQuery):
        self._resolved = resolved
        self.calls = []

    async def run(self, question, session_context=None):
        self.calls.append((question, session_context))
        return self._resolved


def test_interpret_substitutes_resolved_ticker():
    # Rewrite extracted the surface form "Apple"; the proposed filters must carry
    # the resolved ticker (AAPL) so they match the ticker-stamped corpus.
    filters = Filters(company=["Apple"], doc_type=["10-K"])
    resolved = _resolved(companies=[_res("Apple", "resolved", _AAPL)], filters=filters)
    orch = Orchestrator(pipeline=_StubPipeline(resolved))

    interp = asyncio.run(orch.interpret("How did Apple do?"))
    assert interp.proposed_filters.company == ["AAPL"]
    assert interp.proposed_filters.doc_type == ["10-K"]
    assert interp.needs_confirmation is False
    assert interp.query_type == "other"
    assert interp.companies[0].canonical.ticker == "AAPL"


def test_interpret_keeps_surface_form_when_unresolved():
    # Unresolved company stays as typed and forces confirmation, so the analyst
    # can correct it rather than silently searching a non-existent filter value.
    filters = Filters(company=["Acme"])
    resolved = _resolved(companies=[_res("Acme", "not_found")], filters=filters)
    orch = Orchestrator(pipeline=_StubPipeline(resolved))

    interp = asyncio.run(orch.interpret("How did Acme do?"))
    assert interp.proposed_filters.company == ["Acme"]
    assert interp.needs_confirmation is True


def test_interpret_no_company_stays_none():
    resolved = _resolved(filters=Filters(doc_type=["10-K"]))
    orch = Orchestrator(pipeline=_StubPipeline(resolved))

    interp = asyncio.run(orch.interpret("What are the risk factors?"))
    assert interp.proposed_filters.company is None
    assert interp.needs_confirmation is False


# --- answer wiring -------------------------------------------------------------

class _FakeSearchClient:
    def __init__(self, results):
        self._results = results
        self.calls = []

    async def search(self, query, filters, top_k=5):
        self.calls.append((query, filters, top_k))
        return self._results


class _FakeGenerator:
    def __init__(self, generated):
        self._generated = generated
        self.calls = []

    async def generate(self, question, results):
        self.calls.append((question, results))
        return self._generated


def test_answer_retrieves_on_confirmed_filters():
    hit = SearchResult(
        text="Apple risk factors",
        distance=0.1,
        citation=Citation(natural_id="AAPL-10K-2024", company="AAPL", period="2024"),
    )
    fake_search = _FakeSearchClient([hit])
    fake_generated = GeneratedAnswer(answer="Apple faces risk [1]", citations=[1], can_answer=True)
    fake_generator = _FakeGenerator(fake_generated)
    orch = Orchestrator(
        pipeline=_StubPipeline(_resolved()),
        search_client=fake_search,
        generator=fake_generator,
    )

    confirmed = Filters(company=["AAPL"], period=["2024"])
    answer = asyncio.run(orch.answer("risk factors", confirmed, top_k=3))

    assert answer.results == [hit]
    assert answer.generated == fake_generated
    # The confirmed filters (not a re-run of rewrite/resolve) drive retrieval.
    assert fake_search.calls == [("risk factors", confirmed, 3)]
    # Generation runs on the chunks retrieval actually returned.
    assert fake_generator.calls == [("risk factors", [hit])]
