"""Thin FastAPI over the agent — the online-path entry point.

The GraphRAG agent loop with its own in-loop confirm gate:
`POST /agent/ask` runs the loop; if the model targets a company that doesn't
resolve, the search is held and the endpoint returns the pending approval instead
of an answer. The paused run's state travels back to the client as an opaque
`message_history` blob (no server-side store): the client shows the held company
to the analyst and `POST /agent/resume`s with the decision and that blob, and the
loop continues from where it paused.

Run: `uv run uvicorn financial_doc_ai.serving.api:app --host 0.0.0.0 --port 8000`
"""

from typing import Any, Literal

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.tools import ToolDenied

from financial_doc_ai.serving.agent import build_agent
from financial_doc_ai.serving.answer import AnswerBlock, CitedAnswer

app = FastAPI(title="financial-doc-ai")

# Lazy singleton so importing the module (e.g. in tests, which override the
# dependency) doesn't build the agent / read env.
_agent: Agent | None = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


class AskRequest(BaseModel):
    question: str


class HeldCall(BaseModel):
    """One search the loop paused on, for the analyst to confirm."""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]


class ResumeRequest(BaseModel):
    # Echoed back verbatim from a prior held response; opaque to the client.
    message_history: Any
    # tool_call_id -> approve (True) or reject (False).
    approvals: dict[str, bool]


class AgentResponse(BaseModel):
    """Either the finished answer, or the calls held pending approval."""

    status: Literal["answered", "held"]
    # Display text: the answer's blocks joined in order.
    answer: str | None = None
    # The same answer, per attributable block. Each block's `chunk_ids` resolve to
    # the original passages, so a client can offer click-through to source. An
    # abstention is one block with no chunk_ids.
    blocks: list[AnswerBlock] = []
    held: list[HeldCall] = []
    # Present only when held: the paused run's serialized state to send to /resume.
    message_history: Any | None = None


def _to_agent_response(result: Any) -> AgentResponse:
    output = result.output
    if isinstance(output, DeferredToolRequests):
        return AgentResponse(
            status="held",
            held=[
                HeldCall(
                    tool_call_id=call.tool_call_id,
                    tool_name=call.tool_name,
                    args=call.args_as_dict(),
                )
                for call in output.approvals
            ],
            message_history=ModelMessagesTypeAdapter.dump_python(
                result.all_messages(), mode="json"
            ),
        )
    if isinstance(output, CitedAnswer):
        return AgentResponse(
            status="answered", answer=output.joined(), blocks=output.blocks
        )
    # Defensive: a plain-string output (e.g. a guardrail replacement that bypassed
    # the answer contract) still returns as display text.
    return AgentResponse(status="answered", answer=str(output))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/agent/ask")
async def agent_ask(
    req: AskRequest, agent: Agent = Depends(get_agent)
) -> AgentResponse:
    async with agent:  # opens the MCP toolset connections for the run
        result = await agent.run(req.question)
    return _to_agent_response(result)


@app.post("/agent/resume")
async def agent_resume(
    req: ResumeRequest, agent: Agent = Depends(get_agent)
) -> AgentResponse:
    history = ModelMessagesTypeAdapter.validate_python(req.message_history)
    results = DeferredToolResults()
    for tool_call_id, approved in req.approvals.items():
        results.approvals[tool_call_id] = (
            True if approved else ToolDenied("Rejected by the analyst.")
        )
    async with agent:
        result = await agent.run(
            message_history=history, deferred_tool_results=results
        )
    return _to_agent_response(result)
