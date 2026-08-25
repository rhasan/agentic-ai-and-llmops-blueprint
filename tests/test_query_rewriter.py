import vcr
from financial_doc_ai.query_rewriter import QueryRewriter

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


@my_vcr.use_cassette("query_rewrite_single.yaml")
def test_rewrite_single_fact():
    qr = QueryRewriter(model=MODEL, api_base=API_BASE)
    r = qr.rewrite("What was Apple net sales in 2024?")

    assert r.query_type == "other"
    assert r.filters.company == ["Apple"]
    assert r.filters.period == ["2024"]
    assert r.filters.doc_type is None          # not stated -> not inferred
    assert r.filters.version == "current"


@my_vcr.use_cassette("query_rewrite_compare.yaml")
def test_rewrite_compare():
    qr = QueryRewriter(model=MODEL, api_base=API_BASE)
    r = qr.rewrite("Compare Apple and Microsoft revenue in 2024")

    assert r.query_type == "compare"
    assert r.filters.company == ["Apple", "Microsoft"]
    assert r.filters.period == ["2024"]
