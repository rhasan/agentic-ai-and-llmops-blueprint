from pathlib import Path

from financial_doc_ai.storage import VectorStore


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


def test_filter_metadata_is_stamped_on_every_chunk(tmp_path: Path):
  vs = VectorStore(tmp_path / "chroma")
  chunks = [
      {"text": "a", "is_table": False, "headers": {}, "chunk_index": 0},
      {"text": "b", "is_table": False, "headers": {}, "chunk_index": 1},
  ]
  fields = {"company": "AAPL", "doc_type": "10-K", "period": "2024", "version": "current"}
  vs.add_chunks("DOC-1", chunks, [[0.1], [0.2]], "test/model", filter_metadata=fields)

  got = vs.collection.get(where={"natural_id": "DOC-1"})
  for m in got["metadatas"]:
      assert m["company"] == "AAPL"
      assert m["doc_type"] == "10-K"
      assert m["period"] == "2024"
      assert m["version"] == "current"
