"""Unit tests for the graph-retrieval provenance recovery.

Pure/offline — no external calls, so no VCR. Mirrors test_graph_indexer.py:
the GraphRAG-running function (GraphSearch.search) is validated by running it
live, not tested here. What we lock is the one subtle, breakable part — turning
DRIFT's ordinal `sources.id` back into our real chunk id and id-joining it to the
chunk store for citations. That's the cross-source citation/dedup invariant.
"""

from pathlib import Path

import pandas as pd

from financial_doc_ai.graph_retrieval.search import _load_chunk_index, recover_passages
from financial_doc_ai.storage import ChunkStore


def _chunk(i: int, text: str) -> dict:
    return {"text": text, "is_table": False, "headers": {"h1": "Risk Factors"}, "chunk_index": i}


def _seed_store(tmp_path: Path) -> ChunkStore:
    store = ChunkStore(tmp_path)
    store.put(
        chunks=[_chunk(0, "chunk zero"), _chunk(1, "chunk one")],
        source="edgar",
        natural_id="ACC-1",
        fetched_at="2026-01-01T00:00:00Z",
        source_metadata={},
        metadata={"company": "AAPL", "doc_type": "10-K", "period": "2025", "version": "current"},
    )
    return store


def test_load_chunk_index_keys_and_fields(tmp_path: Path):
    index = _load_chunk_index(_seed_store(tmp_path))

    assert set(index) == {"ACC-1:0", "ACC-1:1"}
    entry = index["ACC-1:1"]
    assert entry["text"] == "chunk one"
    assert entry["company"] == "AAPL"
    assert entry["doc_type"] == "10-K"
    assert entry["period"] == "2025"
    assert entry["version"] == "current"
    assert entry["chunk_index"] == 1
    assert entry["headers"] == {"h1": "Risk Factors"}


def test_recover_passages_maps_short_id_to_chunk_id(tmp_path: Path):
    chunk_index = _load_chunk_index(_seed_store(tmp_path))
    # human_readable_id (== DRIFT's short_id) -> our chunk id, as the text_units
    # table provides it.
    hrid_to_chunk_id = {0: "ACC-1:0", 1: "ACC-1:1"}
    # Real drift_search shape: flat context, `sources.id` holds short_ids as
    # strings (as the DataFrame renders them).
    context_data = {
        "entities": pd.DataFrame({"id": ["7"], "title": ["Apple"]}),  # not `sources`
        "sources": pd.DataFrame({"id": ["1", "0"], "text": ["x", "y"]}),
    }

    results = recover_passages(context_data, hrid_to_chunk_id, chunk_index, top_k=10)

    assert [r.citation.natural_id for r in results] == ["ACC-1", "ACC-1"]
    assert [r.citation.chunk_index for r in results] == [1, 0]  # order preserved
    assert all(r.source == "graphrag" for r in results)
    assert all(r.distance is None for r in results)
    assert results[0].text == "chunk one"
    assert results[0].citation.company == "AAPL"


def test_recover_passages_accepts_nested_form(tmp_path: Path):
    # Fallback shape (per-sub-query nesting) other methods/versions may emit.
    chunk_index = _load_chunk_index(_seed_store(tmp_path))
    context_data = {"sub-query A": {"sources": pd.DataFrame({"id": [0]})}}

    results = recover_passages(context_data, {0: "ACC-1:0"}, chunk_index, top_k=10)

    assert [r.citation.chunk_index for r in results] == [0]


def test_recover_passages_dedups_and_caps(tmp_path: Path):
    chunk_index = _load_chunk_index(_seed_store(tmp_path))
    hrid_to_chunk_id = {0: "ACC-1:0", 1: "ACC-1:1"}
    # Same short_id repeated -> deduped to one passage.
    context_data = {"sources": pd.DataFrame({"id": ["0", "1", "0"]})}

    deduped = recover_passages(context_data, hrid_to_chunk_id, chunk_index, top_k=10)
    assert [r.citation.chunk_index for r in deduped] == [0, 1]

    capped = recover_passages(context_data, hrid_to_chunk_id, chunk_index, top_k=1)
    assert len(capped) == 1


def test_recover_passages_skips_unknown_short_id(tmp_path: Path):
    chunk_index = _load_chunk_index(_seed_store(tmp_path))
    hrid_to_chunk_id = {0: "ACC-1:0"}  # short_id 99 maps to nothing
    context_data = {"sources": pd.DataFrame({"id": ["99", "0"]})}

    results = recover_passages(context_data, hrid_to_chunk_id, chunk_index, top_k=10)

    assert [r.citation.chunk_index for r in results] == [0]


def test_recover_passages_handles_empty_context():
    assert recover_passages({}, {}, {}, top_k=10) == []
    assert recover_passages("not a dict", {}, {}, top_k=10) == []
