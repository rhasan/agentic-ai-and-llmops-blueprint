"""FastAPI wiring: request models, serialization, dependency override.

Hermetic — the orchestrator is replaced via dependency override with a fake, so no
pipeline / MCP / network. Asserts the two endpoints accept their bodies and return
the orchestrator's output as JSON. The real orchestrator+MCP path is the
in-container smoke, not here.
"""

from fastapi.testclient import TestClient

from financial_doc_ai.query.rewriter import Filters, QueryRewrite
from financial_doc_ai.retrieval.search import Citation, SearchResult
from financial_doc_ai.serving.api import app, get_orchestrator
from financial_doc_ai.serving.orchestrator import Answer, Interpretation


class _FakeOrchestrator:
    def __init__(self):
        self.answer_calls = []

    def interpret(self, question, session_context=None):
        return Interpretation(
            query_type="other",
            rewritten_query=question,
            proposed_filters=Filters(company=["AAPL"], doc_type=["10-K"]),
            companies=[],
            needs_confirmation=True,
            reasons=["Could not resolve company 'Acme'."],
        )

    async def answer(self, question, confirmed_filters, top_k=5):
        self.answer_calls.append((question, confirmed_filters, top_k))
        return Answer(results=[
            SearchResult(
                text="Apple risk factors",
                distance=0.1,
                citation=Citation(natural_id="AAPL-10K-2024", company="AAPL", period="2024"),
            )
        ])


def _client(fake):
    app.dependency_overrides[get_orchestrator] = lambda: fake
    return TestClient(app)


def test_health():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}


def test_interpret_returns_proposed_filters_and_gate():
    client = _client(_FakeOrchestrator())
    try:
        resp = client.post("/interpret", json={"question": "How did Acme do?"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["proposed_filters"]["company"] == ["AAPL"]
    assert body["needs_confirmation"] is True
    assert body["reasons"]


def test_answer_retrieves_on_posted_filters():
    fake = _FakeOrchestrator()
    client = _client(fake)
    try:
        resp = client.post(
            "/answer",
            json={
                "question": "risk factors",
                "filters": {"company": ["AAPL"], "period": ["2024"]},
                "top_k": 3,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0]["citation"]["natural_id"] == "AAPL-10K-2024"
    # The posted (confirmed) filters + top_k reach the orchestrator verbatim.
    _, filters, top_k = fake.answer_calls[0]
    assert filters == Filters(company=["AAPL"], period=["2024"])
    assert top_k == 3
