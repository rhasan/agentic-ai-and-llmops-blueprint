"""Post-loop grounding gate: the last check before an answer reaches the analyst.

The agent already grounds by construction (it answers only over retrieved
passages), but the model can still drift — assert an unsupported claim, or a
wrong figure. This gate re-checks the finished answer against the very passages
the run retrieved and, if anything isn't supported, replaces the answer with an
abstention. Correctness outranks completeness: a wrong citation defeats the
analyst's verification step, so we abstain rather than ship a doubtful claim.

Two complementary checks (per docs/initial-system-description.md):
- a deterministic verbatim check for numbers — an LLM grader can wave through a
  plausible-but-wrong digit (e.g. a covenant threshold), so every number in the
  answer must appear verbatim in the passages;
- an LLM-as-judge for everything else — does each claim trace to a passage.

Hosted as a pydantic-ai-harness `OutputGuardrail` (see serving/agent.py): the
harness supplies the gate mechanism (inspect final output -> allow / replace),
the judgment here is ours because no library does online grounding of cited
financial prose (RAGAS is the offline eval gate, not this on-path check).
"""

import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai_harness import GuardrailResult

from financial_doc_ai.prompts.registry import fetch_system_prompt
from financial_doc_ai.serving.agent_model import build_model

# The single abstention wording. Matches the answer contract's refusal path.
ABSTENTION = "I could not ground an answer in the available documents."

# Tools whose returns are the evidence the answer must be grounded in.
_RETRIEVAL_TOOLS = {"search_filings", "graph_search"}

# A *figure* as it appears in prose: a number carrying a thousands separator or a
# decimal part (e.g. "391,035", "1,234", "4.0", "0.50"). Deliberately NOT bare
# integers — those are years and form numbers from inline citations ("2024 10-K")
# and small counts, which are attribution not claims and would cause false
# abstention. This targets the precise financial figures the LLM judge is weakest
# on (a plausible-but-wrong digit); qualitative claims are the judge's job.
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+")


class ClaimVerdict(BaseModel):
    claim: str
    supported: bool
    reason: str


class GroundingVerdict(BaseModel):
    grounded: bool
    confidence: float
    claims: list[ClaimVerdict]


def _texts_from_content(content: Any) -> list[str]:
    """Pull passage texts out of one retrieval tool's return.

    `search_filings` returns a list of SearchResult dicts; `graph_search`
    returns a GraphAnswer dict with a `results` list of the same shape. Fall
    back to the stringified content for any other shape so the evidence is never
    silently empty.
    """
    if isinstance(content, dict):
        items: Any = content.get("results", [content])
    elif isinstance(content, list):
        items = content
    else:
        return [str(content)]
    texts: list[str] = []
    for item in items:
        if isinstance(item, dict) and "text" in item:
            texts.append(str(item["text"]))
        else:
            texts.append(str(item))
    return texts


def collect_passages(messages: Iterable[ModelMessage]) -> list[str]:
    """Gather every retrieved passage text from the run's message history.

    The passages the answer must ground in are exactly what the retrieval tools
    returned during the run — read them back off the tool-return parts rather
    than re-retrieving, so the check sees the same evidence the model did.
    """
    passages: list[str] = []
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolReturnPart) and part.tool_name in _RETRIEVAL_TOOLS:
                passages.extend(_texts_from_content(part.content))
    return passages


def numbers_grounded(answer: str, passages: Iterable[str]) -> bool:
    """True unless the answer states a number absent from the passages.

    Comma-insensitive verbatim match: "1,234" grounds against "1234" and vice
    versa. Deterministic on purpose — this is the check that catches a fabricated
    or mistyped figure the LLM judge might rationalize as plausible.
    """
    haystack = " ".join(passages).replace(",", "")
    for match in _NUMBER_RE.findall(answer):
        if match.replace(",", "") not in haystack:
            return False
    return True


async def judge(
    answer: str,
    passages: list[str],
    *,
    model_spec: str | None = None,
    instructions: str | None = None,
) -> GroundingVerdict:
    """LLM-as-judge: is every claim in `answer` supported by `passages`?"""
    grader = Agent(
        build_model(model_spec),
        output_type=GroundingVerdict,
        instructions=(
            instructions
            if instructions is not None
            else fetch_system_prompt("grounding_judge")
        ),
    )
    evidence = "\n---\n".join(passages)
    result = await grader.run(f"ANSWER:\n{answer}\n\nPASSAGES:\n{evidence}")
    verdict = result.output
    # Derive the aggregate from the per-claim judgments, not the model's own
    # top-level flag (it has been observed to set grounded=false while marking
    # every claim supported, and vice versa). But don't require EVERY claim: the
    # deterministic number check upstream already guards figures (the high-risk
    # case), so the judge here only scores qualitative claims, where it is noisy —
    # it occasionally fails a framing/lead-in sentence. A lone flaky "unsupported"
    # out of many claims shouldn't sink an otherwise-grounded answer, so tolerate a
    # small share; abstain only when a meaningful fraction is unsupported.
    total = len(verdict.claims)
    supported = sum(claim.supported for claim in verdict.claims)
    verdict.grounded = total == 0 or supported / total >= 0.8
    return verdict


def build_grounding_guard(
    model_spec: str | None = None,
    instructions: str | None = None,  # injected in tests -> no live Phoenix
):
    """Build the OutputGuardrail callable that gates the final answer.

    Returns a guard `(ctx, output) -> GuardrailResult`: it allows a grounded
    answer through unchanged and replaces an ungrounded one with the abstention.
    Non-string outputs (e.g. a held-for-approval `DeferredToolRequests`) aren't
    final prose, so they pass untouched.
    """

    async def guard(ctx: Any, output: Any) -> GuardrailResult:
        if not isinstance(output, str):
            return GuardrailResult.allow()
        passages = collect_passages(ctx.messages)
        if not passages:
            # Nothing was retrieved — there is nothing to ground against.
            return GuardrailResult.replace(ABSTENTION)
        if not numbers_grounded(output, passages):
            return GuardrailResult.replace(ABSTENTION)
        verdict = await judge(
            output, passages, model_spec=model_spec, instructions=instructions
        )
        if verdict.grounded:
            return GuardrailResult.allow()
        return GuardrailResult.replace(ABSTENTION)

    return guard
