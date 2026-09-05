"""Build the GraphRAG knowledge graph from the existing chunk store.

Reuses the chunks we already produced (one chunk = one GraphRAG document, keyed
by our chunk id) so graph-retrieved passages dedup against the vector store by
the same id. Models are injected from the same .env model strings the rest of
the app uses (litellm "provider/model"), via a factory rather than the
settings.yaml, so switching Ollama/Azure/Bedrock is one .env change.
"""

import asyncio
import json
import os
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
from graphrag.api.index import build_index
from graphrag.config.load_config import load_config
from graphrag_llm.config import ModelConfig

from financial_doc_ai.storage import ChunkStore

DATA_ROOT = Path("/app/data")
GRAPHRAG_ROOT = "/app/config/graphrag"  # holds settings.yaml (tracked config)


@contextmanager
def preserve_cwd():
    """Restore the working directory on exit.

    GraphRAG's `load_config` does an `os.chdir(root_dir)` and never restores it,
    which silently leaks into the rest of the process (e.g. other code — or other
    tests — resolving relative paths against the wrong dir). We wrap the GraphRAG
    calls so the chdir lasts exactly as long as needed: indexing keeps it through
    `build_index` (its prompt paths are relative to root_dir), query restores it
    right after `load_config` (drift needs no relative-path reads).
    """
    prev = os.getcwd()
    try:
        yield
    finally:
        os.chdir(prev)


def _split_model(spec: str) -> tuple[str, str]:
    """Split a litellm "provider/model" string into (provider, model).

    Same convention as .env (ollama/… , azure/… , bedrock/…); split on the
    first "/" so the model's own ":" tag (Ollama) or internal "/" is preserved.
    """
    provider, _, model = spec.partition("/")
    if not model:
        raise ValueError(f"model spec missing provider prefix: {spec!r}")
    return provider, model


def _model_config(spec: str, api_base: str | None) -> ModelConfig:
    """Map a litellm model string to a GraphRAG ModelConfig.

    GraphRAG is a litellm passthrough, so the provider token maps straight to
    model_provider — no alias translation. Ollama is reached over its
    OpenAI-compatible endpoint (litellm 'ollama' -> GraphRAG 'openai' + /v1).
    Cloud providers (azure/bedrock/openai) read their own credentials from env
    the way litellm does; provider-specific extras (Azure api_version, Bedrock
    region) get wired here when those paths are actually exercised.
    """
    provider, model = _split_model(spec)
    if provider == "ollama":
        base = (api_base or os.environ["LLM_API_BASE"]).rstrip("/")
        return ModelConfig(
            model_provider="openai",
            model=model,
            api_base=f"{base}/v1",
            api_key="ollama",  # OpenAI client needs a non-empty key; Ollama ignores it
        )
    if provider == "azure":
        # `model` is the Azure deployment name (azure/<deployment>); key + version
        # come from the same env vars litellm uses elsewhere in the app.
        return ModelConfig(
            model_provider="azure",
            model=model,
            api_base=api_base,
            api_version=os.environ["AZURE_API_VERSION"],
            api_key=os.environ["AZURE_API_KEY"],
        )
    if provider == "bedrock":
        # AWS auth is not api-key based: litellm/boto3 read AWS_ACCESS_KEY_ID /
        # AWS_SECRET_ACCESS_KEY / AWS_REGION_NAME from env (injected by compose from
        # .env). ModelConfig still requires a non-empty api_key under its default
        # api_key auth, so pass a dummy — bedrock ignores it. No api_base (litellm
        # derives the endpoint from the region).
        return ModelConfig(model_provider="bedrock", model=model, api_key="bedrock")
    # openai + others: litellm reads the provider's own key from env.
    return ModelConfig(model_provider=provider, model=model, api_base=api_base)


def _configure_models(config) -> None:
    """Inject completion + embedding models (and the embedding dim) from env.

    Keeps every .env→config model wiring in one place, so switching provider is a
    single .env change. The embedding dimension is set here too: GraphRAG only
    auto-detects it on its CLI path (`validate_config_names`), not on the
    `build_index` API path we use, so the lancedb index would keep the 3072
    default and reject our vectors. We source it from EMBEDDING_DIM (the dim of
    EMBEDDING_MODEL) instead — model + dim switch together in .env.
    """
    config.completion_models = {
        "default_completion_model": _model_config(
            os.environ["GRAPHRAG_CHAT_MODEL"], os.environ.get("LLM_API_BASE")
        )
    }
    config.embedding_models = {
        "default_embedding_model": _model_config(
            os.environ["EMBEDDING_MODEL"], os.environ.get("EMBEDDING_API_BASE")
        )
    }
    # index_schema is already populated (3 defaults at vector_size 3072) by the
    # time load_config returns, so set both the parent and each schema.
    dim = int(os.environ["EMBEDDING_DIM"])
    config.vector_store.vector_size = dim
    for schema in config.vector_store.index_schema.values():
        schema.vector_size = dim


def _document_title(source_metadata: dict) -> str:
    """Human-readable source label for a filing, shared by all its chunks.

    Chunk identity lives in `id` ("{natural_id}:{chunk_index}"); the title just
    names the source filing so it reads cleanly in logs/artifacts, e.g.
    "Apple Inc. 10-K (2025-09-27)". Falls back gracefully if a field is missing.
    """
    name = source_metadata.get("company_name") or source_metadata.get("ticker") or "Unknown"
    form = source_metadata.get("form") or "filing"
    period = source_metadata.get("report_date") or source_metadata.get("filing_date") or ""
    return f"{name} {form} ({period})".replace(" ()", "")


def build_documents_df(chunk_store: ChunkStore, max_chunks: int | None = None) -> pd.DataFrame:
    """Flatten the chunk store into GraphRAG's `documents` input DataFrame.

    One row per chunk: id = "{natural_id}:{chunk_index}" (becomes the text_unit
    document_id — our citation key), text = the chunk text, title = the source
    filing label. `max_chunks` caps the row count for cheap dev runs (unset =
    the whole corpus).
    """
    rows: list[dict] = []
    with chunk_store.manifest_path.open() as f:
        for line in f:
            rec = json.loads(line)
            payload = json.loads((chunk_store.root / rec["storage_path"]).read_text(encoding="utf-8"))
            nid = payload["natural_id"]
            title = _document_title(rec.get("source_metadata", {}))
            for c in payload["chunks"]:
                rows.append({"id": f"{nid}:{c['chunk_index']}", "title": title, "text": c["text"]})
    df = pd.DataFrame(rows, columns=["id", "title", "text"])
    if max_chunks is not None:
        df = df.head(max_chunks)
    return df


def build_graph_index() -> int:
    """Load config, inject models, and run the full GraphRAG index over the chunks.

    Full rebuild each run — GraphRAG indexes the whole input set, not
    per-document like the other stores (incremental update is a later
    refinement). Returns the number of documents indexed.
    """
    max_chunks_env = os.environ.get("GRAPHRAG_MAX_CHUNKS")
    max_chunks = int(max_chunks_env) if max_chunks_env else None
    df = build_documents_df(ChunkStore(DATA_ROOT), max_chunks=max_chunks)
    # Keep cwd = root_dir through build_index (relative indexing prompt paths),
    # then restore it — load_config's chdir would otherwise leak process-wide.
    with preserve_cwd():
        config = load_config(root_dir=Path(GRAPHRAG_ROOT))
        _configure_models(config)
        asyncio.run(build_index(config, input_documents=df))
    return len(df)
