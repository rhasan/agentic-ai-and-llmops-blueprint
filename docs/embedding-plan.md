# Embedding & Vector Index — Build Plan

Concrete plan to build the next ingestion stage: embed chunks and store them in a
vector index. Pick up from here.

## Goal

Add an `embedded_chunks` Dagster asset (deps on `chunked_filings`) that reads each
document's chunks, embeds their text, and writes the vectors + metadata into a local
Chroma vector store. DAG becomes: raw → parsed → chunked → **embedded**.

## Key decisions (settled)

- **Embedding client: LiteLLM.** One unified `embedding()` call; switch providers by
  changing the model string, not code. Ollama now, Azure OpenAI later via config only.
- **Model: `nomic-embed-text` via Ollama**, configurable through env (`EMBEDDING_MODEL`).
- **Ollama runs as its own compose service** (not on the host). Removes the
  per-machine dependency (one laptop has Ollama, one doesn't) and the
  `host.docker.internal` problem. Reachable at `http://ollama:11434` by service name.
- **Vector store: Chroma**, persisted to `data/chroma/` (gitignored, on the bind mount).
- **Provider switch note:** Ollama (`nomic-embed-text`, 768-dim) and Azure
  (`text-embedding-3-small`, 1536-dim) produce different-sized vectors. Switching
  providers requires **re-embedding** — the index is not reusable across models. Store
  the embedding model name in chunk metadata so the index is traceable.

## Config surface (`.env`)

```
EMBEDDING_MODEL=ollama/nomic-embed-text     # LiteLLM model string
OLLAMA_API_BASE=http://ollama:11434         # compose service name
```
(Later for Azure: `EMBEDDING_MODEL=azure/<deployment>` + Azure endpoint/key vars.)

## Compose changes (`infra/ingestion/docker-compose.yml`)

Add two services and wire startup order so nothing is manual:

1. **`ollama`** service — image `ollama/ollama`, model data in a named volume
   (`ollama_models:/root/.ollama`) so it persists. Add a healthcheck.
2. **`ollama-pull`** one-shot service — depends on `ollama` being healthy, runs
   `ollama pull nomic-embed-text`, then exits. This is the "no manual pull" step.
3. **`app`** — add `depends_on`:
   - `ollama-pull` with `condition: service_completed_successfully` (waits until the
     model is actually pulled before the pipeline can run).
   - Add `OLLAMA_API_BASE` (already via `.env`).
4. Add `ollama_models` to the top-level `volumes:` block.

Startup chain: **ollama up → model pulled → app starts.** First `up` downloads the
model into the volume (one time); later runs are instant.

## Dependencies to add

```
uv add litellm chromadb
```
(run in the container, then rebuild the image).

## Code to write

1. **`src/financial_doc_ai/embedder.py`** — thin wrapper over LiteLLM `embedding()`.
   Reads `EMBEDDING_MODEL` and `OLLAMA_API_BASE` from env; exposes
   `embed(texts: list[str]) -> list[list[float]]`. Keep it dumb (embed only, no storage),
   same principle as `edgar.py`.
2. **`VectorStore` (Chroma)** — a small wrapper around a Chroma collection persisted to
   `data/chroma/`. Methods: add chunks (id, text, embedding, metadata), and a
   `has_natural_id` check for idempotency. Thin seam so Chroma can be swapped later.
3. **`embedded_chunks` asset** in `definitions.py`, `deps=[chunked_filings]`:
   walk `chunk_manifest.jsonl` → for each doc not yet embedded, load its chunks JSON,
   embed the texts via the embedder, write vectors + metadata (include
   `natural_id`, `chunk_index`, `is_table`, headers, **embedding model name**) to Chroma.
   Idempotent by `natural_id`. Add asset to `Definitions`.

## Verification

1. `docker compose -f infra/ingestion/docker-compose.yml up -d --build` — confirm
   `ollama-pull` completes and `app` starts.
2. Smoke test connectivity from the app container:
   `curl -s http://ollama:11434/api/tags` should list `nomic-embed-text`.
3. Materialize `embedded_chunks` in the Dagster UI; confirm `data/chroma/` is populated
   and the log reports vectors written per document.
4. Re-materialize → should skip already-embedded docs (idempotency).
5. Add a small test embedding one short text and asserting a non-empty vector of the
   expected dimension.

## Build order

1. Compose: add `ollama` + `ollama-pull` services, wire `depends_on`. Bring up, verify
   the model pulls automatically and connectivity works.
2. `uv add litellm chromadb`, rebuild.
3. `embedder.py` + a one-off embed smoke test.
4. `VectorStore` (Chroma).
5. `embedded_chunks` asset; materialize end-to-end.