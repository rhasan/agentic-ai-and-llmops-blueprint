import asyncio

import vcr

from financial_doc_ai.prompts import SEED_DIR, load_manifest
from financial_doc_ai.query.rewriter import QueryRewriter

# Record the real LiteLLM -> Ollama call once, then replay offline.
# Model output is frozen into the cassette, so assertions are deterministic.
my_vcr = vcr.VCR(
    cassette_library_dir="tests/cassettes",
    record_mode="once",
    filter_headers=["Authorization", "api-key"],
)

# Passed explicitly (not from env) so replay works without .env present.
MODEL = "ollama/qwen2.5:3b-instruct"
API_BASE = "http://ollama:11434"

# Inject the seed prompt via the system_prompt seam so tests need no live Phoenix.
_spec = load_manifest()["query_rewrite"]
SEED_PROMPT = (SEED_DIR / _spec["file"]).read_text(encoding="utf-8")


@my_vcr.use_cassette("query_rewrite_single.yaml")
def test_rewrite_single_fact():
    qr = QueryRewriter(model=MODEL, api_base=API_BASE, system_prompt=SEED_PROMPT)
    r = asyncio.run(qr.rewrite("What was Apple net sales in 2024?"))

    assert r.query_type == "other"
    assert r.filters.company == ["Apple"]
    assert r.filters.period == ["2024"]
    assert r.filters.doc_type is None          # not stated -> not inferred
    assert r.filters.version == "current"


@my_vcr.use_cassette("query_rewrite_compare.yaml")
def test_rewrite_compare():
    qr = QueryRewriter(model=MODEL, api_base=API_BASE, system_prompt=SEED_PROMPT)
    r = asyncio.run(qr.rewrite("Compare Apple and Microsoft revenue in 2024"))

    assert r.query_type == "compare"
    assert r.filters.company == ["Apple", "Microsoft"]
    assert r.filters.period == ["2024"]
