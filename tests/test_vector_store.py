from pathlib import Path

from financial_doc_ai.vector_store import VectorStore


def test_add_and_lookup(tmp_path: Path):
  # Real Chroma, isolated in a pytest temp dir — no external service, no network.
  vs = VectorStore(tmp_path / "chroma")
  chunks = [
      {"text": "net sales", "is_table": True, "headers": {}, "chunk_index": 0},
      {"text": "risk factors", "is_table": False,
       "headers": {"h1": "Item 1A"}, "chunk_index": 1},
  ]
  vs.add_chunks("DOC-1", chunks, [[0.1], [0.2]], "test/model")

  assert vs.has_natural_id("DOC-1")
  assert not vs.has_natural_id("MISSING")
  assert vs.collection.count() == 2

  # Metadata must be flat scalars (Chroma rejects nested dicts/None).
  got = vs.collection.get(where={"natural_id": "DOC-1"})
  meta = {m["chunk_index"]: m for m in got["metadatas"]}
  assert meta[1]["h1"] == "Item 1A"          # headers flattened
  assert meta[0]["is_table"] is True
  assert all(m["embedding_model"] == "test/model" for m in got["metadatas"])
