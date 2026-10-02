"""Grounding-gate tests.

Two layers:
- pure (no LLM, no network): passage collection, the deterministic number check,
  and every check that short-circuits before the judge — a block citing nothing, a
  block citing a passage the run never retrieved, and a block whose figure is
  absent from *its own* cited passages;
- VCR + Azure gpt-5.4-mini: the judge verdict and the full mixed path
  (drop → re-synthesize → re-check), recorded once and replayed offline (same
  convention + Azure-host scrub as test_agent.py).

Record in-container on the serving stack (Azure reachable):
    docker compose -f infra/serving/docker-compose.yml run --rm --no-deps -T app \
        uv run pytest tests/test_grounding.py
"""

import asyncio
import re

import vcr
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from financial_doc_ai.prompts import SEED_DIR, load_manifest
from financial_doc_ai.serving.answer import AnswerBlock, CitedAnswer
from financial_doc_ai.serving.grounding import (
    ABSTENTION,
    build_grounding_guard,
    check_blocks,
    collect_passages,
    numbers_grounded,
)

# Same Azure-host scrub as test_agent.py: keep the real resource name out of the
# committed cassette; symmetric so replay still matches.
_AZURE_HOST_RE = re.compile(rb"[a-z0-9-]+\.openai\.azure\.com", re.I)
_AZURE_PLACEHOLDER = b"fake-resource.openai.azure.com"


def _scrub_request(request):
    request.uri = _AZURE_HOST_RE.sub(_AZURE_PLACEHOLDER, request.uri.encode()).decode()
    if "host" in request.headers:
        request.headers["host"] = _AZURE_PLACEHOLDER.decode()
    return request


def _scrub_response(response):
    body = response.get("body", {}).get("string")
    if isinstance(body, bytes):
        response["body"]["string"] = _AZURE_HOST_RE.sub(_AZURE_PLACEHOLDER, body)
    return response


my_vcr = vcr.VCR(
    cassette_library_dir="tests/cassettes",
    record_mode="once",
    filter_headers=["authorization", "api-key"],
    before_record_request=_scrub_request,
    before_record_response=_scrub_response,
    # Match on the request BODY as well as the URI. The gate issues several calls
    # to the same endpoint per run (one judge call per block, plus synthesis and
    # the re-check) and `check_blocks` runs blocks concurrently, so arrival order
    # is not deterministic. Without body matching, replay can hand a judge
    # response to the synthesis call, which then fails to parse as a CitedAnswer.
    match_on=("method", "scheme", "host", "port", "path", "query", "body"),
)


def _cassette(name: str):
    """Open a cassette tolerating repeated playback of an identical request.

    `allow_playback_repeats` is a `use_cassette` argument, not a `VCR()`
    constructor one.
    """
    return my_vcr.use_cassette(name, allow_playback_repeats=True)

MODEL = "azure/gpt-5.4-mini"
_manifest = load_manifest()
JUDGE_PROMPT = (SEED_DIR / _manifest["grounding_judge"]["file"]).read_text(
    encoding="utf-8"
)
SYNTHESIS_PROMPT = (SEED_DIR / _manifest["answer_synthesis"]["file"]).read_text(
    encoding="utf-8"
)

# Two passages from different chunks of the same filing. Keyed by chunk_id, which
# is what a block cites.
CHUNK_SALES = "0000320193-24-000106:12"
CHUNK_RISK = "0000320193-24-000106:47"
PASSAGE_SALES = (
    "Total net sales were $391,035 million in fiscal 2024, compared to "
    "$383,285 million in 2023."
)
# NB: this passage names Apple explicitly. A real filing says "the Company", and
# the judge (correctly) will not equate that with "Apple" — the passage has to
# support the entity the block names, not just the predicate.
PASSAGE_RISK = (
    "Apple Inc.'s products and services may be affected by supply-chain "
    "disruptions and component shortages."
)
PASSAGES = {CHUNK_SALES: PASSAGE_SALES, CHUNK_RISK: PASSAGE_RISK}


def _block(text: str, *chunk_ids: str) -> AnswerBlock:
    return AnswerBlock(text=text, chunk_ids=list(chunk_ids))


def _answer(*blocks: AnswerBlock) -> CitedAnswer:
    return CitedAnswer(blocks=list(blocks))


def _verdicts(answer: CitedAnswer, passages=None):
    """Run the per-block check. Used only for cases that never reach the judge."""
    return asyncio.run(
        check_blocks(
            answer,
            PASSAGES if passages is None else passages,
            model_spec=MODEL,
            instructions=JUDGE_PROMPT,
        )
    )


class _Ctx:
    """Stands in for the harness RunContext — the guard only reads `.messages`."""

    def __init__(self, messages):
        self.messages = messages


def _tool_return(*passages: tuple[str, str], tool_name: str = "search_filings"):
    """One retrieval tool return, shaped like SearchResult.model_dump()."""
    return ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name=tool_name,
                content=[
                    {"text": text, "citation": {"chunk_id": chunk_id}}
                    for chunk_id, text in passages
                ],
                tool_call_id="c1",
            )
        ]
    )


# --- pure: passage collection ----------------------------------------------


def test_collect_passages_keys_by_chunk_id():
    messages = [
        _tool_return((CHUNK_SALES, PASSAGE_SALES)),
        _tool_return((CHUNK_RISK, PASSAGE_RISK), tool_name="graph_search"),
    ]
    assert collect_passages(messages) == PASSAGES


def test_collect_passages_reads_graph_results_wrapper():
    # graph_search returns a GraphAnswer dict whose `results` holds the passages.
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="graph_search",
                    content={
                        "sub_answer": {"answer": "..."},
                        "results": [
                            {
                                "text": PASSAGE_RISK,
                                "citation": {"chunk_id": CHUNK_RISK},
                            }
                        ],
                    },
                    tool_call_id="c2",
                )
            ]
        )
    ]
    assert collect_passages(messages) == {CHUNK_RISK: PASSAGE_RISK}


def test_collect_passages_ignores_non_retrieval_tools():
    assert collect_passages([_tool_return((CHUNK_RISK, PASSAGE_RISK), tool_name="other")]) == {}


# --- pure: the deterministic number check ----------------------------------


def test_numbers_grounded_accepts_present_number():
    assert numbers_grounded("Net sales were $391,035 million.", [PASSAGE_SALES])


def test_numbers_grounded_rejects_absent_number():
    assert not numbers_grounded("Net sales were $500,000 million.", [PASSAGE_SALES])


def test_numbers_grounded_is_comma_insensitive():
    assert numbers_grounded("Net sales were 391035 million.", [PASSAGE_SALES])


# --- pure: checks that short-circuit before the judge ----------------------


def test_block_with_no_citation_is_unsupported():
    verdicts = _verdicts(_answer(_block("Net sales grew in 2024.")))
    assert not verdicts[0].supported
    assert "cites no passage" in verdicts[0].reason


def test_block_citing_unretrieved_passage_is_unsupported():
    # A chunk_id the run never returned: a fabricated citation.
    verdicts = _verdicts(
        _answer(_block("Net sales were $391,035 million in fiscal 2024.", "made-up:99"))
    )
    assert not verdicts[0].supported
    assert "not retrieved" in verdicts[0].reason


def test_block_with_absent_figure_is_unsupported():
    verdicts = _verdicts(
        _answer(_block("Net sales were $500,000 million in fiscal 2024.", CHUNK_SALES))
    )
    assert not verdicts[0].supported
    assert "figure" in verdicts[0].reason


def test_figure_grounded_in_a_different_passage_is_unsupported():
    """The spec divergence this redesign fixes.

    The figure IS in the retrieved evidence — but in the risk passage's sibling,
    not in the passage this block cites. Grounding against the union (what the old
    gate did) passed this; checking against the cited text rejects it.
    """
    verdicts = _verdicts(
        _answer(_block("Net sales were $391,035 million in fiscal 2024.", CHUNK_RISK))
    )
    assert not verdicts[0].supported
    assert "figure" in verdicts[0].reason


# --- guard control flow that needs no model --------------------------------


def _guard(**kwargs):
    return build_grounding_guard(MODEL, JUDGE_PROMPT, SYNTHESIS_PROMPT, **kwargs)


def test_guard_passes_non_answer_output_untouched():
    # A held-for-approval DeferredToolRequests is not final prose.
    sentinel = object()
    result = asyncio.run(_guard()(_Ctx([]), sentinel))
    assert result.action == "allow"


def test_guard_abstains_when_nothing_was_retrieved():
    answer = _answer(_block("Net sales were $391,035 million.", CHUNK_SALES))
    result = asyncio.run(_guard()(_Ctx([]), answer))
    assert result.replacement.blocks[0].text == ABSTENTION


def test_guard_abstains_when_every_block_fails_deterministically():
    # Both blocks fail before the judge, so this needs no model call.
    answer = _answer(
        _block("Net sales were $500,000 million.", CHUNK_SALES),
        _block("Apple raised its dividend.", "made-up:99"),
    )
    ctx = _Ctx([_tool_return((CHUNK_SALES, PASSAGE_SALES), (CHUNK_RISK, PASSAGE_RISK))])
    result = asyncio.run(_guard()(ctx, answer))
    assert result.replacement.blocks[0].text == ABSTENTION
    assert result.replacement.blocks[0].chunk_ids == []


def test_guard_abstains_on_empty_answer():
    result = asyncio.run(_guard()(_Ctx([]), _answer()))
    assert result.replacement.blocks[0].text == ABSTENTION


# --- judge + full path (VCR) ------------------------------------------------


def test_judge_supports_a_grounded_block():
    answer = _answer(
        _block("Total net sales were $391,035 million in fiscal 2024.", CHUNK_SALES)
    )
    with _cassette("grounding_block_supported.yaml"):
        verdicts = _verdicts(answer)
    assert verdicts[0].supported


def test_judge_rejects_an_unsupported_qualitative_block():
    # The cited passage says nothing about a dividend. No figure, so the number
    # check passes vacuously and the judge has to catch it.
    answer = _answer(_block("Apple raised its quarterly dividend.", CHUNK_SALES))
    with _cassette("grounding_block_unsupported.yaml"):
        verdicts = _verdicts(answer)
    assert not verdicts[0].supported


def test_guard_allows_a_fully_grounded_answer_unchanged():
    answer = _answer(
        _block("Total net sales were $391,035 million in fiscal 2024.", CHUNK_SALES),
        _block(
            "Apple's products and services may be affected by supply-chain "
            "disruptions and component shortages.",
            CHUNK_RISK,
        ),
    )
    ctx = _Ctx([_tool_return((CHUNK_SALES, PASSAGE_SALES), (CHUNK_RISK, PASSAGE_RISK))])
    with _cassette("grounding_guard_all_grounded.yaml"):
        result = asyncio.run(_guard()(ctx, answer))
    # Allowed, not replaced: nothing was dropped, so synthesis must be skipped.
    assert result.action == "allow"


def test_guard_drops_bad_block_and_resynthesizes():
    answer = _answer(
        _block("Total net sales were $391,035 million in fiscal 2024.", CHUNK_SALES),
        # Fails deterministically (fabricated citation), so it must not survive.
        _block("Apple raised its quarterly dividend to $0.50 per share.", "made-up:99"),
        _block(
            "Apple's products and services may be affected by supply-chain "
            "disruptions and component shortages.",
            CHUNK_RISK,
        ),
    )
    ctx = _Ctx([_tool_return((CHUNK_SALES, PASSAGE_SALES), (CHUNK_RISK, PASSAGE_RISK))])
    with _cassette("grounding_guard_mixed.yaml"):
        result = asyncio.run(_guard()(ctx, answer))

    text = result.replacement.joined()
    assert result.replacement.blocks
    assert text != ABSTENTION
    # The dropped block's content is gone; the surviving figure is still there.
    assert "dividend" not in text.lower()
    assert "391,035" in text
    # Every surviving block still carries a real citation.
    assert all(b.chunk_ids for b in result.replacement.blocks)
