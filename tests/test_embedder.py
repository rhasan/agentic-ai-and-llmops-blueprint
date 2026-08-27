import types

import vcr

from financial_doc_ai.ingestion.embedder import Embedder

# Records a real Ollama embedding call once, then replays offline. Body is not
# matched (default) so it isn't sensitive to request serialization.
my_vcr = vcr.VCR(cassette_library_dir="tests/cassettes", record_mode="once")

# Model/api_base are pinned to what the cassette was recorded against — on replay
# VCR intercepts before any network, so these need not resolve locally.
MODEL = "ollama/nomic-embed-text"
API_BASE = "http://ollama:11434"


@my_vcr.use_cassette("embed_texts.yaml")
def test_embed_returns_one_vector_per_input():
    out = Embedder(model=MODEL, api_base=API_BASE).embed(["net sales", "risk factors"])
    assert len(out) == 2
    # Real nomic-embed-text vectors: equal length, non-empty.
    assert len(out[0]) == len(out[1]) > 0


def test_embed_preserves_input_order(monkeypatch):
    # NOT a VCR case: this asserts embed() re-sorts a *deliberately out-of-order*
    # provider response by index. Real Ollama returns rows in order, so a recording
    # can't reproduce the condition — the crafted response IS the test.
    fake = types.SimpleNamespace(data=[
        {"index": 1, "embedding": [0.2]},
        {"index": 0, "embedding": [0.1]},
    ])
    monkeypatch.setattr("financial_doc_ai.ingestion.embedder.litellm.embedding", lambda **kw: fake)
    out = Embedder(model="test/model", api_base=None).embed(["a", "b"])
    assert out == [[0.1], [0.2]]
