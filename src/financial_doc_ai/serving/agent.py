"""GraphRAG agent: a model-driven loop over the two retrieval MCP tools.

The core pydantic-ai `Agent` *is* the agent loop — no custom loop. The two
retrieval servers attach directly as native `MCPToolset`s (their server-side
tool descriptions carry the routing), so nothing is re-wrapped. Given a
question, the model decomposes it, calls `search_filings` / `graph_search` per
sub-question, and synthesizes a cited prose answer as its final turn. Model is
chosen by `AGENT_MODEL` via the build_model factory.

Confirm gate: `search_filings` is wrapped with pydantic-ai's `approval_required`
(a library primitive, not a hand-rolled loop). Before each vector search we
resolve the company filter the model proposes; if it doesn't resolve cleanly
(not_found / ambiguous) the call is held for human approval instead of running —
the one mis-extraction the grounding check can't catch (a correct answer over
the *wrong* document). This is why `output_type` includes `DeferredToolRequests`:
a held call surfaces as an approval request; `resume()` feeds the decision back.
Clean, unambiguous filters (and all `graph_search` calls) run uninterrupted.
See docs/specs/graphrag-financial-doc-ai.md.
"""

import os
from typing import Any

from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelMessage
from pydantic_ai.tools import ToolDefinition, ToolDenied
from pydantic_ai_harness import OutputGuardrail

from financial_doc_ai.prompts.registry import fetch_system_prompt
from financial_doc_ai.query.resolver import CompanyResolver
from financial_doc_ai.serving.agent_model import build_model
from financial_doc_ai.serving.answer import CitedAnswer
from financial_doc_ai.serving.grounding import build_grounding_guard

# DRIFT graph search runs ~90-125s (primer + sequential follow-up LLM calls);
# set the graph toolset's read timeout well clear of that so a latency spike on
# the cloud model can't abort the call. Vector search is fast (default timeout).
GRAPH_READ_TIMEOUT = 600

_resolver = CompanyResolver()


def _needs_company_confirmation(
    ctx: RunContext[Any], tool_def: ToolDefinition, tool_args: dict[str, Any]
) -> bool:
    """Hold a `search_filings` call when its company filter doesn't resolve cleanly.

    Reuses the deterministic `CompanyResolver`: any `not_found` / `ambiguous`
    outcome means the model may have targeted the wrong (or no) company, so the
    call needs a human OK before it retrieves. No company filter -> nothing to
    confirm.
    """
    companies = tool_args.get("company") or []
    resolutions = _resolver.resolve(companies)
    return any(r.outcome in ("not_found", "ambiguous") for r in resolutions)


def build_agent(
    model_spec: str | None = None,
    instructions: str | None = None,   # injected in tests -> no live Phoenix
    search_url: str | None = None,
    graph_url: str | None = None,
    grounding_instructions: str | None = None,  # judge prompt seam (tests)
    synthesis_instructions: str | None = None,  # synthesis prompt seam (tests)
    judge_model_spec: str | None = None,
) -> Agent:
    search = MCPToolset(search_url or os.environ["SEARCH_MCP_URL"]).approval_required(
        _needs_company_confirmation
    )
    graph = MCPToolset(
        graph_url or os.environ["GRAPH_MCP_URL"], read_timeout=GRAPH_READ_TIMEOUT
    )
    # The grounding judge runs on its own model: `JUDGE_MODEL` if set, else the
    # loop's model. Lets a cheaper/faster model do the verbatim grounding check
    # without changing the answering model. build_model(None) -> AGENT_MODEL.
    judge_model = judge_model_spec or os.environ.get("JUDGE_MODEL") or model_spec
    return Agent(
        build_model(model_spec),
        toolsets=[search, graph],
        # The answer is a list of independently-cited blocks, not prose: that is
        # what lets the grounding gate check (and drop) one claim at a time rather
        # than passing judgement on the whole answer. See serving/answer.py.
        output_type=[CitedAnswer, DeferredToolRequests],
        # Post-loop grounding gate: check each block against its own cited
        # passages, drop what isn't supported, re-synthesize the rest, abstain if
        # nothing survives. See grounding.py.
        capabilities=[
            OutputGuardrail(
                guard=build_grounding_guard(
                    judge_model, grounding_instructions, synthesis_instructions
                )
            )
        ],
        instructions=(
            instructions
            if instructions is not None
            else fetch_system_prompt("agent_orchestration")
        ),
    )


async def resume(
    agent: Agent,
    requests: DeferredToolRequests,
    message_history: list[ModelMessage],
    *,
    approved: bool,
    denial_message: str = "Rejected by the analyst.",
):
    """Feed the human decision on held calls back into the run and continue.

    Applies one blanket decision to every held approval (the gate holds a single
    company-filter call at a time). Re-runs from the prior `message_history` with
    no new prompt — the model resumes from where it paused.
    """
    results = DeferredToolResults()
    for call in requests.approvals:
        results.approvals[call.tool_call_id] = (
            True if approved else ToolDenied(denial_message)
        )
    async with agent:
        return await agent.run(
            message_history=message_history, deferred_tool_results=results
        )
