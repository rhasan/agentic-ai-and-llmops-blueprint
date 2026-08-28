import asyncio

import vcr

from financial_doc_ai.prompts import SEED_DIR, load_manifest
from financial_doc_ai.query.pipeline import QueryPipeline
from financial_doc_ai.query.resolver import CompanyResolver
from financial_doc_ai.query.rewriter import QueryRewriter

# Real rewriter (LiteLLM -> Ollama, recorded once) + real resolver; only Phoenix
# is bypassed via the system_prompt seam.
my_vcr = vcr.VCR(
    cassette_library_dir="tests/cassettes",
    record_mode="once",
    filter_headers=["Authorization", "api-key"],
)

MODEL = "ollama/qwen2.5:3b-instruct"
API_BASE = "http://ollama:11434"

_spec = load_manifest()["query_rewrite"]
SEED_PROMPT = (SEED_DIR / _spec["file"]).read_text(encoding="utf-8")


def _pipeline() -> QueryPipeline:
    return QueryPipeline(
        rewriter=QueryRewriter(model=MODEL, api_base=API_BASE, system_prompt=SEED_PROMPT),
        resolver=CompanyResolver(),
    )


@my_vcr.use_cassette("query_rewrite_single.yaml")
def test_run_resolves_extracted_companies():
    result = asyncio.run(_pipeline().run("What was Apple net sales in 2024?"))

    assert result.rewrite.filters.company == ["Apple"]
    assert [c.outcome for c in result.companies] == ["resolved"]
    assert result.companies[0].canonical.ticker == "AAPL"


@my_vcr.use_cassette("pipeline_no_company.yaml")
def test_run_with_no_company_filter_resolves_nothing():
    result = asyncio.run(_pipeline().run("What are the main risk factors?"))

    assert result.rewrite.filters.company is None
    assert result.companies == []
