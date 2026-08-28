"""Thin FastAPI over the orchestrator — the online-path entry point.

Two endpoints exercise the stateless HITL flow (see docs/retrieval-and-serving.md):
`POST /interpret` proposes filters and says whether the analyst must confirm;
`POST /answer` retrieves on the (possibly corrected) filters the client sends back.
No web UI yet; a client renders the proposed filters and posts them to /answer.

Run: `uv run uvicorn financial_doc_ai.serving.api:app --host 0.0.0.0 --port 8000`
"""

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from financial_doc_ai.query.rewriter import Filters
from financial_doc_ai.serving.orchestrator import Answer, Interpretation, Orchestrator

app = FastAPI(title="financial-doc-ai")

# Lazy singleton so importing the module (e.g. in tests, which override the
# dependency) doesn't construct the pipeline / fetch prompts / read env.
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


class InterpretRequest(BaseModel):
    question: str
    session_context: str | None = None


class AnswerRequest(BaseModel):
    question: str
    filters: Filters
    top_k: int = 5


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/interpret")
def interpret(
    req: InterpretRequest, orch: Orchestrator = Depends(get_orchestrator)
) -> Interpretation:
    return orch.interpret(req.question, req.session_context)


@app.post("/answer")
async def answer(
    req: AnswerRequest, orch: Orchestrator = Depends(get_orchestrator)
) -> Answer:
    return await orch.answer(req.question, req.filters, req.top_k)
