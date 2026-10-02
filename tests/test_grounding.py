"""Grounding-gate tests.

Two layers, matching the two checks the gate runs:
- pure (no LLM, no network): the deterministic number check and passage
  collection from a run's message history;
- VCR + Azure gpt-5.4-mini: the LLM-as-judge verdict, recorded once and replayed
  offline (same convention + Azure-host scrub as test_agent.py).

Record in-container on the serving stack (Azure reachable):
    docker compose -f infra/serving/docker-compose.yml run --rm --no-deps -T app \
        uv run pytest tests/test_grounding.py
"""

import asyncio
import re

import vcr
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from financial_doc_ai.prompts import SEED_DIR, load_manifest
from financial_doc_ai.serving.grounding import (
    collect_passages,
    judge,
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
)

MODEL = "azure/gpt-5.4-mini"
JUDGE_PROMPT = (
    SEED_DIR / load_manifest()["grounding_judge"]["file"]
).read_text(encoding="utf-8")

# A small, self-contained evidence set the judge reasons over.
PASSAGES = [
    "Total net sales were $391,035 million in fiscal 2024, compared to "
    "$383,285 million in 2023. (AAPL 2024 10-K)",
    "The Company's products and services may be affected by supply-chain "
    "disruptions and component shortages. (AAPL 2024 10-K)",
]


# --- pure checks (no LLM) ---------------------------------------------------


def test_numbers_grounded_accepts_present_number():
    assert numbers_grounded("Net sales were $391,035 million.", PASSAGES)


def test_numbers_grounded_rejects_absent_number():
    # A figure that never appears in the passages must fail the deterministic check.
    assert not numbers_grounded("Net sales were $500,000 million.", PASSAGES)


def test_numbers_grounded_is_comma_insensitive():
    assert numbers_grounded("Net sales were 391035 million.", PASSAGES)


def test_collect_passages_reads_retrieval_tool_returns():
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="search_filings",
                    content=[{"text": "passage one"}, {"text": "passage two"}],
                    tool_call_id="c1",
                ),
                ToolReturnPart(
                    tool_name="graph_search",
                    content={"results": [{"text": "graph passage"}]},
                    tool_call_id="c2",
                ),
            ]
        )
    ]
    assert collect_passages(messages) == ["passage one", "passage two", "graph passage"]


# --- LLM-as-judge (VCR) -----------------------------------------------------


def _judge(answer: str):
    async def go():
        return await judge(
            answer, PASSAGES, model_spec=MODEL, instructions=JUDGE_PROMPT
        )

    return asyncio.run(go())


def test_judge_passes_a_grounded_answer():
    answer = "Apple's total net sales were $391,035 million in fiscal 2024 (AAPL 2024 10-K)."
    with my_vcr.use_cassette("grounding_judge_grounded.yaml"):
        verdict = _judge(answer)
    assert verdict.grounded


def test_judge_fails_an_unsupported_claim():
    # The passages say nothing about a dividend; the judge must flag it.
    answer = "Apple raised its quarterly dividend to $0.50 per share (AAPL 2024 10-K)."
    with my_vcr.use_cassette("grounding_judge_ungrounded.yaml"):
        verdict = _judge(answer)
    assert not verdict.grounded
