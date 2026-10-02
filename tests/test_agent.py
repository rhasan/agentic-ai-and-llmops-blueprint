"""Agent-loop test: records the real interaction (Azure gpt-5.4-mini + the two
MCP servers) once with VCR, then replays offline.

Exercises the whole loop end to end — the model receives the two MCP toolsets,
decides which to call, gets real retrieved passages, and synthesizes a cited
prose answer as its final turn. Recording the real calls (per the VCR
convention) pins the model's tool-calling shape and catches API drift.

Record in-container on the serving stack (Azure reachable + the retrieval /
graph-retrieval stacks up on llm-net):
    docker compose -f infra/serving/docker-compose.yml run --rm -T app \
        uv run pytest tests/test_agent.py
"""

import asyncio
import re

import vcr
from pydantic_ai import DeferredToolRequests

from financial_doc_ai.prompts import SEED_DIR, load_manifest
from financial_doc_ai.serving.agent import build_agent, resume
from financial_doc_ai.serving.answer import CitedAnswer

# Keep the real Azure resource name out of the committed cassette. Rewrite any
# `*.openai.azure.com` host to a placeholder. vcrpy applies this filter both when
# recording (before storing) and on replay (to the live request before matching),
# so the substitution is symmetric and replay still matches — while nothing
# identifiable is stored. Host-agnostic, so the real name never appears here either.
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
    # Scrub the Azure secret from the committed cassette (Azure uses `api-key`).
    filter_headers=["authorization", "api-key"],
    before_record_request=_scrub_request,
    before_record_response=_scrub_response,
)

# Passed explicitly (not from env) so replay works without .env present. Azure
# deployment name is literally the model name; build_model wires the provider.
MODEL = "azure/gpt-5.4-mini"
# In-container MCP URLs the recording was made against (URI is the VCR match key).
SEARCH_URL = "http://retrieval-app-1:8001/mcp"
GRAPH_URL = "http://graph-retrieval-app-1:8002/mcp"

# Inject the seed prompts via the instructions seams so the test needs no Phoenix
# (the orchestration prompt for the loop, the judge prompt for the grounding gate).
_manifest = load_manifest()
SEED_PROMPT = (SEED_DIR / _manifest["agent_orchestration"]["file"]).read_text(encoding="utf-8")
JUDGE_PROMPT = (SEED_DIR / _manifest["grounding_judge"]["file"]).read_text(encoding="utf-8")
SYNTHESIS_PROMPT = (SEED_DIR / _manifest["answer_synthesis"]["file"]).read_text(encoding="utf-8")


def _build():
    return build_agent(
        model_spec=MODEL,
        instructions=SEED_PROMPT,
        search_url=SEARCH_URL,
        graph_url=GRAPH_URL,
        grounding_instructions=JUDGE_PROMPT,
        synthesis_instructions=SYNTHESIS_PROMPT,
    )


def _run(question: str):
    """Run to the first stop: either a CitedAnswer or a held approval."""
    agent = _build()

    async def go():
        async with agent:  # opens the MCP toolset connections for the run
            result = await agent.run(question)
        return result.output

    return asyncio.run(go())


def test_agent_answers_single_document_question():
    # Apple resolves cleanly -> no confirmation -> the loop runs straight through
    # to a cited answer that survives the grounding gate.
    with my_vcr.use_cassette("agent_single_document.yaml"):
        answer = _run("What business risks did Apple describe in its 2024 10-K?")
    assert isinstance(answer, CitedAnswer)
    assert answer.blocks
    # Every block is attributed, which is what makes the answer checkable.
    assert all(block.chunk_ids for block in answer.blocks)
    assert answer.joined().strip()


def test_unresolved_company_pauses_for_approval():
    # A company the resolver doesn't know (only Apple is registered) can't be
    # verified, so the search_filings call is held rather than run: the run ends
    # with a DeferredToolRequests instead of prose.
    with my_vcr.use_cassette("agent_unresolved_company.yaml"):
        output = _run("What business risks did Tesla describe in its 2024 10-K?")
    assert isinstance(output, DeferredToolRequests)
    assert output.approvals  # a held call awaiting the analyst's OK


def test_resume_after_approval_completes():
    # Approving a held call lets retrieval proceed. Each unresolved company search
    # is held on its own, so a client keeps approving until the run finishes — the
    # loop here mirrors that and asserts it terminates in a CitedAnswer.
    agent = _build()

    async def go():
        async with agent:
            result = await agent.run(
                "What business risks did Tesla describe in its 2024 10-K?"
            )
        assert isinstance(result.output, DeferredToolRequests)  # first stop = held
        for _ in range(5):  # bound the approvals so a stuck loop fails fast
            if not isinstance(result.output, DeferredToolRequests):
                break
            result = await resume(
                agent, result.output, result.all_messages(), approved=True
            )
        return result.output

    with my_vcr.use_cassette("agent_resume_after_approval.yaml"):
        output = asyncio.run(go())
    assert isinstance(output, CitedAnswer)
    assert output.blocks
