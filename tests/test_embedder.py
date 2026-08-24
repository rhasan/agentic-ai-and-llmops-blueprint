import types

from financial_doc_ai.embedder import Embedder


def test_embed_preserves_input_order(monkeypatch):
  # LiteLLM may return rows out of order; embed() must re-sort by index so the
  # output lines up with the input texts.
  fake = types.SimpleNamespace(data=[
      {"index": 1, "embedding": [0.2]},
      {"index": 0, "embedding": [0.1]},
  ])
  monkeypatch.setattr(
      "financial_doc_ai.embedder.litellm.embedding", lambda **kw: fake
  )
  # Pass model explicitly so the test doesn't depend on env vars.
  out = Embedder(model="test/model", api_base=None).embed(["a", "b"])
  assert out == [[0.1], [0.2]]
