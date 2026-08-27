# Embedding & Vector Index Strategy

How chunked documents are embedded and stored for retrieval. The ingestion DAG is
raw → parsed → chunked → **embedded**: the `embedded_chunks` asset reads each
document's chunks, embeds their text, and writes the vectors + metadata into a local
Chroma vector store.

## Key decisions

- **Embedding client: LiteLLM.** One unified `embedding()` call; switch providers by
  changing the model string, not code. Ollama now, Azure OpenAI later via config only.
- **Model: `nomic-embed-text` via Ollama** (768-dim), set through `EMBEDDING_MODEL`.
- **Ollama runs as its own compose service** (not on the host). Removes the
  per-machine dependency (one laptop has Ollama, one doesn't) and the
  `host.docker.internal` problem. Reachable at `http://ollama:11434` by service name.
- **Vector store: Chroma**, persisted to `data/chroma/` (gitignored, on the bind mount).
- **Provider switch note:** Ollama (`nomic-embed-text`, 768-dim) and Azure
  (`text-embedding-3-small`, 1536-dim) produce different-sized vectors. Switching
  providers requires **re-embedding** — the index is not reusable across models. The
  embedding model name is stored in chunk metadata so the index stays traceable.

## Config surface (`.env`)

```
EMBEDDING_MODEL=ollama/nomic-embed-text     # LiteLLM model string
EMBEDDING_API_BASE=http://ollama:11434      # generic (provider-agnostic) api base
```
(Later for Azure: `EMBEDDING_MODEL=azure/<deployment>` + Azure endpoint/key vars.)

## Compose (`infra/ingestion/docker-compose.yml`)

Three services wire the startup order so nothing is manual:

1. **`ollama`** — model data in a named volume (`ollama_models:/root/.ollama`) so it
   persists, plus a healthcheck. Builds from `Dockerfile.ollama`, which installs the
   corporate root CA when present so it can pull through a TLS-inspecting proxy.
2. **`ollama-pull`** one-shot — depends on `ollama` being healthy, runs
   `ollama pull nomic-embed-text`, then exits. The "no manual pull" step.
3. **`app`** — `depends_on: ollama-pull` with `condition: service_completed_successfully`,
   so the pipeline can't run until the model is present.

Startup chain: **ollama up → model pulled → app starts.** First `up` downloads the
model into the volume (one time); later runs are instant.

## Code

1. **`src/financial_doc_ai/ingestion/embedder.py`** — `Embedder`, a thin wrapper over LiteLLM
   `embedding()`. Reads `EMBEDDING_MODEL` + api base from env; exposes
   `embed(texts: list[str]) -> list[list[float]]`. Sorts `response.data` by index so
   output order matches input. Embed-only, no storage — same dumb-client principle as
   `edgar.py`.
2. **`src/financial_doc_ai/storage/vector_store.py`** — `VectorStore`, a wrapper around a Chroma
   collection (`chunks`) persisted to `data/chroma/`. `add_chunks` (id =
   `natural_id:chunk_index`, flattens `headers` into scalar metadata, records the
   embedding-model name per chunk) and `has_natural_id` for idempotency. Thin seam so
   Chroma can be swapped later.
3. **`embedded_chunks` asset** (`definitions.py`, `deps=[chunked_filings]`): walk
   `chunk_manifest.jsonl` → for each doc not yet embedded, load its chunks JSON, embed
   the texts, write vectors + metadata (`natural_id`, `chunk_index`, `is_table`,
   headers, embedding model name) to Chroma. Idempotent by `natural_id`.

## Tests

- `tests/test_embedder.py` — unit; mocks the LiteLLM provider, asserts `embed()`
  preserves input order (the index-sort logic).
- `tests/test_vector_store.py` — hermetic integration against a real ephemeral Chroma
  (in a pytest `tmp_path`): round-trip `add_chunks` → `has_natural_id` / count / flat
  metadata. No external service, no network.
