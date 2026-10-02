"""Post-loop grounding gate: the last check before an answer reaches the analyst.

The agent already grounds by construction (it answers only over retrieved
passages), but the model can still drift — assert an unsupported claim, or a wrong
figure. This gate re-checks the finished answer against the very passages the run
retrieved and, if anything isn't supported, drops it. Correctness outranks
completeness: a wrong citation defeats the analyst's verification step, so a
doubtful claim is never shipped.

The answer arrives as independently-cited blocks (`serving/answer.py`), which lets
this run per block against *that block's own cited passages* — the "matches the
cited text" check docs/initial-system-description.md asks for. Three checks per
block, cheapest first, so most failures cost no tokens at all:

1. every cited `chunk_id` was actually returned by a tool this run — catches a
   fabricated citation;
2. every figure in the block appears verbatim in its cited passages — an LLM grader
   will wave through a plausible-but-wrong digit (a covenant threshold, a net-sales
   line), exact matching will not;
3. an LLM judge decides whether those passages support the statement.

A partial failure does not sink the answer. The surviving blocks are re-synthesized
into a coherent answer and re-checked by the same function; only if that fails (or
nothing survives) do we abstain. When nothing was dropped the synthesis and
re-check are skipped entirely, so the common case costs exactly one judge pass.

Hosted as a pydantic-ai-harness `OutputGuardrail` (see serving/agent.py): the
harness supplies the gate mechanism (inspect final output -> allow / replace), the
judgment here is ours because no library does online grounding of cited financial
prose (RAGAS is the offline eval gate, not this on-path check).

See docs/specs/grounding-redesign.md for the design and what it replaced.
"""

import asyncio
import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai_harness import GuardrailResult

from financial_doc_ai.prompts.registry import fetch_system_prompt
from financial_doc_ai.serving.agent_model import build_model
from financial_doc_ai.serving.answer import AnswerBlock, CitedAnswer

# The single abstention wording. Matches the answer contract's refusal path.
ABSTENTION = "I could not ground an answer in the available documents."

# Tools whose returns are the evidence the answer must be grounded in.
_RETRIEVAL_TOOLS = {"search_filings", "graph_search"}

# A *figure* as it appears in prose: a number carrying a thousands separator or a
# decimal part (e.g. "391,035", "1,234", "4.0", "0.50"). Deliberately NOT bare
# integers — those are years and small counts, which are context rather than
# claims and would cause false abstention. This targets the precise financial
# figures the LLM judge is weakest on; qualitative claims are the judge's job.
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+")


class BlockVerdict(BaseModel):
    """Why one block was kept or dropped."""

    index: int
    supported: bool
    reason: str


class _BlockJudgment(BaseModel):
    """The judge's structured reply for a single block."""

    supported: bool
    reason: str


def abstention() -> CitedAnswer:
    """The refusal, in the answer contract's own shape.

    A single uncited block: there is nothing to attribute, and the API renders it
    as plain text with no citations.
    """
    return CitedAnswer(blocks=[AnswerBlock(text=ABSTENTION, chunk_ids=[])])


def _passages_from_content(content: Any) -> dict[str, str]:
    """Pull `{chunk_id: text}` out of one retrieval tool's return.

    `search_filings` returns a list of SearchResult dicts; `graph_search` returns a
    GraphAnswer dict with a `results` list of the same shape. Both carry
    `citation.chunk_id` (a computed field, so it survives `model_dump()`). A
    passage without a chunk_id cannot be cited and is therefore not evidence.
    """
    if isinstance(content, dict):
        items: Any = content.get("results", [content])
    elif isinstance(content, list):
        items = content
    else:
        return {}

    passages: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        chunk_id = (item.get("citation") or {}).get("chunk_id")
        if text is not None and chunk_id:
            passages[str(chunk_id)] = str(text)
    return passages


def collect_passages(messages: Iterable[ModelMessage]) -> dict[str, str]:
    """Gather every retrieved passage from the run, keyed by chunk_id.

    Read back off the tool-return parts rather than re-retrieving, so the check
    sees exactly the evidence the model saw. Keying by chunk_id is what lets a
    block be checked against its own citations instead of the whole pile.
    """
    passages: dict[str, str] = {}
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolReturnPart) and part.tool_name in _RETRIEVAL_TOOLS:
                passages.update(_passages_from_content(part.content))
    return passages


def numbers_grounded(text: str, passages: Iterable[str]) -> bool:
    """True unless `text` states a number absent from `passages`.

    Comma-insensitive verbatim match: "1,234" grounds against "1234" and vice
    versa. Deterministic on purpose — this is the check that catches a fabricated
    or mistyped figure the LLM judge might rationalize as plausible.
    """
    haystack = " ".join(passages).replace(",", "")
    for match in _NUMBER_RE.findall(text):
        if match.replace(",", "") not in haystack:
            return False
    return True


def _build_judge(model_spec: str | None, instructions: str | None) -> Agent:
    return Agent(
        build_model(model_spec),
        output_type=_BlockJudgment,
        instructions=(
            instructions
            if instructions is not None
            else fetch_system_prompt("grounding_judge")
        ),
    )


async def check_blocks(
    answer: CitedAnswer,
    passages: dict[str, str],
    *,
    model_spec: str | None = None,
    instructions: str | None = None,
) -> list[BlockVerdict]:
    """Verify every block against its own cited passages.

    Blocks are independent, so they are checked concurrently. The two deterministic
    checks run first and short-circuit without a model call.
    """
    judge = _build_judge(model_spec, instructions)

    async def check_one(index: int, block: AnswerBlock) -> BlockVerdict:
        if not block.chunk_ids:
            return BlockVerdict(
                index=index, supported=False, reason="block cites no passage"
            )

        missing = [cid for cid in block.chunk_ids if cid not in passages]
        if missing:
            # Cited something this run never retrieved: a fabricated citation.
            return BlockVerdict(
                index=index,
                supported=False,
                reason=f"cited passage(s) not retrieved: {', '.join(missing)}",
            )

        cited = [passages[cid] for cid in block.chunk_ids]
        if not numbers_grounded(block.text, cited):
            return BlockVerdict(
                index=index,
                supported=False,
                reason="a figure is absent from the cited passage(s)",
            )

        evidence = "\n---\n".join(cited)
        result = await judge.run(
            f"STATEMENT:\n{block.text}\n\nPASSAGES:\n{evidence}"
        )
        return BlockVerdict(
            index=index,
            supported=result.output.supported,
            reason=result.output.reason,
        )

    return list(
        await asyncio.gather(
            *(check_one(i, b) for i, b in enumerate(answer.blocks))
        )
    )


async def synthesize(
    kept: list[AnswerBlock],
    *,
    model_spec: str | None = None,
    instructions: str | None = None,
) -> CitedAnswer:
    """Rewrite the surviving blocks into one coherent answer.

    Returns the same type it takes, so the result is re-checkable by
    `check_blocks` with no separate code path. The prompt forbids introducing any
    fact not present in the input blocks; the re-check is what enforces it.
    """
    writer = Agent(
        build_model(model_spec),
        output_type=CitedAnswer,
        instructions=(
            instructions
            if instructions is not None
            else fetch_system_prompt("answer_synthesis")
        ),
    )
    payload = "\n\n".join(
        f"[block {i}] cites={block.chunk_ids}\n{block.text}"
        for i, block in enumerate(kept)
    )
    result = await writer.run(f"GROUNDED BLOCKS:\n{payload}")
    return result.output


def build_grounding_guard(
    model_spec: str | None = None,
    instructions: str | None = None,  # judge prompt; injected in tests
    synthesis_instructions: str | None = None,  # synthesis prompt; same
):
    """Build the OutputGuardrail callable that gates the final answer.

    Returns a guard `(ctx, output) -> GuardrailResult`. Non-`CitedAnswer` outputs
    (e.g. a held-for-approval `DeferredToolRequests`) aren't final prose, so they
    pass untouched.
    """

    async def guard(ctx: Any, output: Any) -> GuardrailResult:
        if not isinstance(output, CitedAnswer):
            return GuardrailResult.allow()
        if not output.blocks:
            return GuardrailResult.replace(abstention())

        passages = collect_passages(ctx.messages)
        if not passages:
            # Nothing was retrieved — there is nothing to ground against.
            return GuardrailResult.replace(abstention())

        verdicts = await check_blocks(
            output, passages, model_spec=model_spec, instructions=instructions
        )
        kept = [
            block
            for block, verdict in zip(output.blocks, verdicts, strict=True)
            if verdict.supported
        ]

        if not kept:
            return GuardrailResult.replace(abstention())
        if len(kept) == len(output.blocks):
            # Nothing dropped: ship as written, and skip the extra two calls.
            return GuardrailResult.allow()

        rewritten = await synthesize(
            kept, model_spec=model_spec, instructions=synthesis_instructions
        )
        if not rewritten.blocks:
            return GuardrailResult.replace(abstention())

        # Synthesis is an LLM call too, so it can drift — re-check it the same way.
        recheck = await check_blocks(
            rewritten, passages, model_spec=model_spec, instructions=instructions
        )
        if all(verdict.supported for verdict in recheck):
            return GuardrailResult.replace(rewritten)
        # No retry loop: abstain. "Abstain over guess" is the design rule, and
        # drop-and-re-synthesize is unbounded.
        return GuardrailResult.replace(abstention())

    return guard
