# GraphRAG config

Config + prompts for the offline graph-ingestion path. Design rationale lives in
`docs/specs/graphrag-financial-doc-ai.md`; this file is the runbook.

- `settings.yaml` — GraphRAG index config. No model blocks (injected from `.env`
  in `ingestion/graph_indexer.py`); chunking disabled (one of our chunks = one
  text unit); prompts pointed at `prompts/`.
- `prompts/` — the three auto-tuned prompts (`extract_graph.txt`,
  `summarize_descriptions.txt`, `community_report.txt`). Tracked in git.

There are **two** GraphRAG steps. Both run **inside the ingestion container** — never
on the host (paths are `/app/...`, Azure creds come from `.env` via compose, the
`graphrag` package is in the container venv, and the host is Zscaler-proxied).

## Step 1 — Prompt auto-tune (setup, run once, manual)

Generates the extraction prompts from a sample of our own chunks — the model writes
the persona, the **entity-type list**, and few-shot examples adapted to the corpus.
This is a one-off setup step, **not** a Dagster asset, so it does not run
automatically. Re-run it only when the corpus or ontology changes.

> **This is a native GraphRAG feature** ("auto templating"), exposed as both a CLI
> (`graphrag prompt-tune`) and an API (`graphrag.api.prompt_tune.generate_indexing_prompts`).
> We use it to **derive the entity types and relationship-extraction examples** from
> our corpus instead of hand-writing them. GraphRAG runs the whole workflow —
> detect domain → generate persona → discover entity types → generate few-shot
> examples → assemble the prompts. Our `graph_prompt_tune.py` is only a thin adapter:
> it feeds GraphRAG our chunks (as its input sample) and our `.env` model config, then
> saves the three prompts it returns.

```bash
docker compose -f infra/ingestion/docker-compose.yml exec -T app \
  uv run python -m financial_doc_ai.ingestion.graph_prompt_tune
```

- Output lands in `prompts/` (the repo is bind-mounted at `/app`, so it shows up in
  your working tree to review + commit).
- It tunes over the **full** chunk store, ignoring the `GRAPHRAG_MAX_CHUNKS` dev cap,
  so the prompts stay representative.

**Then review `prompts/extract_graph.txt`** — see `docs/specs/graphrag-financial-doc-ai.md`
("Setup phase") for what to check. Key point: the entity types are **baked into that
file** (its type line + examples), not held in `settings.yaml` — so to change the
ontology, edit `extract_graph.txt`, and keep all four copies of the type list
identical. Few-shot examples teach more than the list, so prefer re-tuning on the
full corpus over hand-adding a type the examples never demonstrate.

## Step 2 — Build the graph index (pipeline)

The `graph_index` Dagster asset (`ingestion/definitions.py`) reads the chunk store
and builds the graph using the prompts above.

```bash
# dev: cap the input (set GRAPHRAG_MAX_CHUNKS in .env, e.g. 15) to stabilize cheaply
docker compose -f infra/ingestion/docker-compose.yml exec -T app \
  uv run dagster asset materialize --select graph_index -m financial_doc_ai.ingestion.definitions
```

Artifacts land in `data/graphrag/output/` (Parquet: documents, text_units, entities,
relationships, communities, community_reports). Full-corpus runs cost ~$7 and take
~12 min on Azure; unset `GRAPHRAG_MAX_CHUNKS` for the final run.
