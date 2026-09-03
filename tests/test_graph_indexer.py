"""Unit tests for the GraphRAG input builder + model factory.

Pure/offline — no external calls, so no VCR. The two things worth locking:
  * build_documents_df keeps our chunk id ("{natural_id}:{chunk_index}"), which
    becomes text_unit.document_id and is the cross-source citation/dedup key.
  * the model factory maps our .env "provider/model" strings to GraphRAG's
    ModelConfig (the "switch provider from .env, not code" decision).
The GraphRAG-running functions (build_graph_index, tune_prompts, the Dagster
asset) are validated by running, not tested here.
"""

from pathlib import Path

import pytest

from financial_doc_ai.ingestion.graph_indexer import (
    GRAPHRAG_ROOT,
    _configure_models,
    _document_title,
    _model_config,
    _split_model,
    build_documents_df,
)
from financial_doc_ai.storage import ChunkStore


def _chunk(i: int, text: str) -> dict:
    return {"text": text, "is_table": False, "headers": {}, "chunk_index": i}


def _put_filing(store: ChunkStore, natural_id: str, source_metadata: dict, texts: list[str]):
    return store.put(
        chunks=[_chunk(i, t) for i, t in enumerate(texts)],
        source="edgar",
        natural_id=natural_id,
        fetched_at="2026-01-01T00:00:00Z",
        source_metadata=source_metadata,
    )


# --- build_documents_df ------------------------------------------------------


def test_id_and_columns_preserve_chunk_key(tmp_path: Path):
    store = ChunkStore(tmp_path)
    _put_filing(
        store,
        "ACC-1",
        {"company_name": "Apple Inc.", "form": "10-K", "report_date": "2025-09-27"},
        ["chunk zero", "chunk one", "chunk two"],
    )

    df = build_documents_df(store)

    assert list(df.columns) == ["id", "title", "text"]
    # The invariant: id == "{natural_id}:{chunk_index}" (becomes text_unit.document_id).
    assert df["id"].tolist() == ["ACC-1:0", "ACC-1:1", "ACC-1:2"]
    assert df["text"].tolist() == ["chunk zero", "chunk one", "chunk two"]
    assert df["title"].tolist() == ["Apple Inc. 10-K (2025-09-27)"] * 3


def test_max_chunks_caps_rows(tmp_path: Path):
    store = ChunkStore(tmp_path)
    _put_filing(
        store,
        "ACC-1",
        {"company_name": "Apple Inc.", "form": "10-K", "report_date": "2025-09-27"},
        ["a", "b", "c"],
    )

    df = build_documents_df(store, max_chunks=2)

    assert len(df) == 2
    assert df["id"].tolist() == ["ACC-1:0", "ACC-1:1"]


def test_title_drops_empty_period(tmp_path: Path):
    store = ChunkStore(tmp_path)
    _put_filing(store, "ACC-1", {"company_name": "Apple Inc.", "form": "10-K"}, ["a"])

    df = build_documents_df(store)

    # No report_date/filing_date -> the "(...)" is dropped, not left empty.
    assert df["title"].tolist() == ["Apple Inc. 10-K"]


def test_title_falls_back_to_ticker(tmp_path: Path):
    store = ChunkStore(tmp_path)
    _put_filing(store, "ACC-1", {"ticker": "AAPL", "form": "10-K", "report_date": "2025-09-27"}, ["a"])

    df = build_documents_df(store)

    assert df["title"].tolist() == ["AAPL 10-K (2025-09-27)"]


def test_document_title_defaults_when_all_missing():
    # Nothing to build from -> graceful placeholders, still no empty "()".
    assert _document_title({}) == "Unknown filing"


# --- model factory (_split_model / _model_config) ----------------------------


def test_split_model_preserves_tag():
    # Split on the FIRST "/" so Ollama's ":tag" (and any internal "/") survives.
    assert _split_model("ollama/qwen2.5:3b-instruct") == ("ollama", "qwen2.5:3b-instruct")
    assert _split_model("azure/gpt-5.4-mini") == ("azure", "gpt-5.4-mini")
    assert _split_model("bedrock/us.anthropic/claude") == ("bedrock", "us.anthropic/claude")


def test_split_model_requires_provider_prefix():
    with pytest.raises(ValueError):
        _split_model("no-prefix")


def test_model_config_ollama():
    mc = _model_config("ollama/nomic-embed-text", "http://ollama:11434")
    # litellm 'ollama' -> GraphRAG 'openai' over the OpenAI-compatible /v1 endpoint.
    assert mc.model_provider == "openai"
    assert mc.model == "nomic-embed-text"
    assert mc.api_base == "http://ollama:11434/v1"
    assert mc.api_key == "ollama"


def test_model_config_azure(monkeypatch):
    monkeypatch.setenv("AZURE_API_VERSION", "2025-04-01-preview")
    monkeypatch.setenv("AZURE_API_KEY", "test-key")

    mc = _model_config("azure/gpt-5.4-mini", "https://x.openai.azure.com/")

    assert mc.model_provider == "azure"
    assert mc.model == "gpt-5.4-mini"  # the Azure deployment name
    assert mc.api_base == "https://x.openai.azure.com/"
    assert mc.api_version == "2025-04-01-preview"
    assert mc.api_key == "test-key"


def test_model_config_bedrock():
    # AWS auth is not api-key based (litellm reads AWS_* creds from env), so we pass
    # a dummy api_key just to satisfy ModelConfig validation; bedrock ignores it.
    mc = _model_config("bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0", None)
    assert mc.model_provider == "bedrock"
    assert mc.model == "anthropic.claude-3-5-sonnet-20240620-v1:0"
    assert mc.api_key  # non-empty dummy so validation passes
    assert mc.api_base is None  # litellm derives the endpoint from AWS_REGION_NAME


# --- embedding dimension wiring (_configure_models) --------------------------


def test_configure_models_sets_embedding_dim(monkeypatch):
    # GraphRAG only auto-syncs vector_size on its CLI path, not the build_index API
    # we use, so _configure_models sets it from EMBEDDING_DIM. Verify it overrides
    # the 3072 default on both the parent and every pre-populated index schema.
    from pathlib import Path

    from graphrag.config.load_config import load_config

    monkeypatch.setenv("GRAPHRAG_CHAT_MODEL", "ollama/qwen2.5:3b-instruct")
    monkeypatch.setenv("EMBEDDING_MODEL", "ollama/nomic-embed-text")
    monkeypatch.setenv("LLM_API_BASE", "http://ollama:11434")
    monkeypatch.setenv("EMBEDDING_API_BASE", "http://ollama:11434")
    monkeypatch.setenv("EMBEDDING_DIM", "768")

    config = load_config(root_dir=Path(GRAPHRAG_ROOT))
    assert config.vector_store.vector_size == 3072  # GraphRAG default before we set it

    _configure_models(config)

    assert config.vector_store.vector_size == 768
    assert config.vector_store.index_schema  # populated by GraphRAG's validator
    assert all(s.vector_size == 768 for s in config.vector_store.index_schema.values())
