import asyncio

import vcr

from financial_doc_ai.prompts import SEED_DIR, load_manifest
from financial_doc_ai.retrieval.search import Citation, SearchResult
from financial_doc_ai.serving.generator import AnswerGenerator

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
_spec = load_manifest()["answer_generation"]
SEED_PROMPT = (SEED_DIR / _spec["file"]).read_text(encoding="utf-8")

_RESULTS = [
    SearchResult(
        text="The Company's business is subject to the risks of doing business "
        "internationally, including... currency fluctuations and compliance with "
        "U.S. and foreign laws and regulations.",
        distance=0.1,
        citation=Citation(
            natural_id="AAPL-10K-2024-1", company="Apple", doc_type="10-K", period="2024"
        ),
    ),
    SearchResult(
        text="The Company depends on component and product manufacturing and "
        "logistical services provided by outsourcing partners, many of which are "
        "located outside of the U.S.",
        distance=0.2,
        citation=Citation(
            natural_id="AAPL-10K-2024-2", company="Apple", doc_type="10-K", period="2024"
        ),
    ),
]


@my_vcr.use_cassette("answer_generation_risk_factors.yaml")
def test_generate_answers_from_passages():
    gen = AnswerGenerator(model=MODEL, api_base=API_BASE, system_prompt=SEED_PROMPT)
    result = asyncio.run(gen.generate("What are Apple's main risk factors?", _RESULTS))

    assert result.can_answer is True
    assert result.answer
    assert all(1 <= c <= len(_RESULTS) for c in result.citations)


def test_generate_abstains_without_results_and_makes_no_llm_call():
    gen = AnswerGenerator(model=MODEL, api_base=API_BASE, system_prompt=SEED_PROMPT)
    result = asyncio.run(gen.generate("What are Apple's main risk factors?", []))

    assert result.can_answer is False
    assert result.citations == []
    assert result.answer
