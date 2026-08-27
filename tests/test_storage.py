import json
from pathlib import Path

from financial_doc_ai.storage import ChunkStore


def test_chunk_store_writes_metadata_block(tmp_path: Path):
    store = ChunkStore(tmp_path)
    chunks = [{"text": "a", "is_table": False, "headers": {}, "chunk_index": 0}]
    metadata = {"company": "AAPL", "doc_type": "10-K", "period": "2024", "version": "current"}

    rec = store.put(
        chunks=chunks,
        source="edgar",
        natural_id="ACC-1",
        fetched_at="2024-01-01T00:00:00Z",
        source_metadata={"cik": 320193, "ticker": "AAPL"},
        metadata=metadata,
    )

    # The chunk file is self-describing: doc-level metadata block + the chunks.
    payload = json.loads((tmp_path / rec.storage_path).read_text(encoding="utf-8"))
    assert payload["metadata"] == metadata
    assert payload["natural_id"] == "ACC-1"
    assert payload["chunks"] == chunks


def test_chunk_store_defaults_metadata_to_empty(tmp_path: Path):
    store = ChunkStore(tmp_path)
    rec = store.put(
        chunks=[{"text": "a", "is_table": False, "headers": {}, "chunk_index": 0}],
        source="edgar",
        natural_id="ACC-2",
        fetched_at="2024-01-01T00:00:00Z",
        source_metadata={},
    )
    payload = json.loads((tmp_path / rec.storage_path).read_text(encoding="utf-8"))
    assert payload["metadata"] == {}
