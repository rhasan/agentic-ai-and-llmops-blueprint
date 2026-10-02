"""FastAPI wiring: request models, serialization, dependency override.

Hermetic — the agent is replaced via dependency override with a fake, so no
model / MCP / network. Asserts the two agent endpoints accept their bodies, hold
on a pending approval, and carry the analyst's decision back into the loop. The
real model+MCP path is test_agent.py, not here.
"""

from fastapi.testclient import TestClient
from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ModelResponse, ToolCallPart

from financial_doc_ai.serving.answer import AnswerBlock, CitedAnswer
from financial_doc_ai.serving.api import app, get_agent


def test_health():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}


# --- agent path (hermetic fake; real LLM+MCP path is test_agent.py) ---------

# A held search: the model targeted a company that didn't resolve, so this call
# is pending the analyst's OK. Its tool_call_id is what the client sends a
# decision for on /agent/resume.
_HELD_CALL = ToolCallPart(
    tool_name="search_filings",
    args={"company": ["Acme"]},
    tool_call_id="call_1",
)


class _FakeAgentResult:
    def __init__(self, output, messages):
        self.output = output
        self._messages = messages

    def all_messages(self):
        return self._messages


class _FakeAgent:
    """Stands in for the pydantic-ai Agent: pauses on the first run, answers on
    resume. Records the approval decision the endpoint fed back."""

    def __init__(self):
        self.resume_decisions = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def run(self, user_prompt=None, *, message_history=None, deferred_tool_results=None):
        if deferred_tool_results is None:  # /agent/ask -> hold the search
            return _FakeAgentResult(
                DeferredToolRequests(approvals=[_HELD_CALL]),
                [ModelResponse(parts=[_HELD_CALL])],
            )
        # /agent/resume -> the decision came back; the loop finishes.
        self.resume_decisions = deferred_tool_results.approvals
        return _FakeAgentResult(
            CitedAnswer(
                blocks=[
                    AnswerBlock(
                        text="Apple's products may be affected by supply-chain disruptions.",
                        chunk_ids=["0000320193-24-000106:47"],
                    )
                ]
            ),
            [],
        )


def _agent_client(fake):
    app.dependency_overrides[get_agent] = lambda: fake
    return TestClient(app)


def test_agent_ask_holds_unresolved_company():
    client = _agent_client(_FakeAgent())
    try:
        resp = client.post("/agent/ask", json={"question": "How did Acme do?"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "held"
    assert body["answer"] is None
    # The client learns which call to confirm and what company it targets.
    assert body["held"][0]["tool_call_id"] == "call_1"
    assert body["held"][0]["args"] == {"company": ["Acme"]}
    # The paused run travels back for the client to echo to /resume.
    assert body["message_history"]


def test_agent_resume_carries_decision_and_finishes():
    fake = _FakeAgent()
    client = _agent_client(fake)
    try:
        held = client.post("/agent/ask", json={"question": "How did Acme do?"}).json()
        resp = client.post(
            "/agent/resume",
            json={
                "message_history": held["message_history"],
                "approvals": {"call_1": True},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "answered"
    assert body["answer"]
    # The answer travels back per block, each carrying the citation a client needs
    # to resolve the passage it came from.
    assert body["blocks"][0]["chunk_ids"] == ["0000320193-24-000106:47"]
    assert body["blocks"][0]["text"] in body["answer"]
    # The analyst's approval reached the loop as an approval for that exact call.
    assert fake.resume_decisions == {"call_1": True}
