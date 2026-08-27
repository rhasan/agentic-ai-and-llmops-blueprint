# CLAUDE.md

Guidance for working in this repository.

## What this repo is

A **blueprint / reference implementation** demonstrating production-grade patterns for an agentic AI application with a full LLMOps stack. It is not a product. The concrete example — a financial-document Q&A system (see `docs/initial-system-description.md`) — is only the **vehicle** used to showcase the patterns.

**Design principle:** drive decisions by "does this demonstrate a production pattern worth showing," NOT by the example's scale. Do not omit a production component just because the example's low volume wouldn't need it. Cost is a hard constraint (personal Azure), so show the production *shape* but size it down and make it tear-downable.

## Working style

- Keep answers concise and plain; match explanation depth to the question, don't over-explain.
- Discuss in chat by default. **Do not write to files unless explicitly asked.**
- The user types code manually for practice — provide specs (what to create + why), then review what they wrote. Don't write the implementation unless asked.

## Docs (read these for context)

- `docs/initial-system-description.md` — the example system (financial-doc Q&A). Its scale figures are properties of the example, not blueprint constraints.
- `docs/data-ingestion.md` — data sources (EDGAR + contracts) and the ingestion architecture decisions.
- `docs/contracts-storyline.md` — the 3 sample contracts, 10-K connections, and cross-document Q&A storyline (*Governance, Equity Plans & Supply Chain Risk*).
- `docs/work-in-progress.md` — **the live progress tracker.** Read this first to see where the build is and what's next.

## Stack & layout

- **Package:** `src/financial_doc_ai/` (uv, Python 3.12), grouped by subsystem to mirror the infra stacks:
  - `ingestion/` — offline batch path (Dagster `definitions.py`, `edgar`, `parser`, `chunker`, `embedder`, `metadata`).
  - `query/` — online path (`pipeline`, `rewriter`, `resolver`; retriever/generator/api land here).
  - `storage/` — persistence shared by both (`stores.py` = Raw/Parsed/Chunk stores, `manifest`, `vector_store`; `__init__` re-exports the public names).
  - `prompts/` — Phoenix registry access (`registry`) + seeding (`seed`).
  - `company_registry.py` — top-level, shared (built offline, read by the resolver).
- **Orchestrator:** Dagster (offline/batch ingestion pipeline). Runs only inside the container.
- **Execution path:** everything runs in Docker (dev == deploy). One compose stack per subsystem under `infra/<stack>/`:
  - `infra/ingestion/` — Dagster batch pipeline (`up --build` → UI at `http://localhost:3000`). Has its own Ollama (embed model only).
  - `infra/ollama/` — shared Ollama + model pulls (`nomic-embed-text` + `qwen2.5:3b-instruct`); `infra/serving/` — online query path; `infra/observability/` — Phoenix (prompt registry + tracing). These share the external `llm-net` network.
- **Storage:** local FS now (`data/`, gitignored), JSONL manifest; migrate to cloud (Blob) + SQLite/DB later via the storage seam.

## Conventions

- Storage goes through `RawStore` (`src/financial_doc_ai/storage/`): content-addressed raw bytes + append-only JSONL manifest; idempotent by content hash; never overwrite (old versions are audit evidence).
- External clients (e.g. `edgar.py`) stay "dumb" — fetch only, no storage logic. Storage lives in the store classes.
- **Config vs derived reference data:** hand-maintained inputs go in git-tracked `config/` (e.g. `config/companies.toml` = what to ingest); data fetched at runtime goes in gitignored `data/reference/` (e.g. `company_tickers.json`, latest-wins overwrite with a sha256 change-check). Don't hardcode lookups that belong in config.
- `EDGAR_USER_AGENT` comes from `.env` (see `.env.example`), injected into the container by compose.

## Testing

- **VCR.py for all external I/O — no mocking or faking.** Any test that calls an external API/system and uses the output records the real interaction once (`record_mode="once"`) and replays offline. Recording real payloads exercises the logic against realistic shapes and catches API drift; hand-written fixtures silently diverge.
  - Record cassettes **in-container**, where SEC/Ollama are reachable (local host is Zscaler-proxied): `docker compose -f infra/<stack>/docker-compose.yml exec -T app uv run pytest <tests>`. For online-path tests hitting `http://ollama:11434`, use the `llm-net` serving stack (`docker compose -f infra/serving/docker-compose.yml run --rm --no-deps -T app uv run pytest ...`). Cassettes bind-mount to `tests/cassettes/` and replay offline.
  - Pre-seeding on-disk state (e.g. a stale cached file to trigger an update path) is plain test setup, not mocking.
  - `allow_playback_repeats=True` is a `use_cassette(...)` arg, not a `VCR()` constructor arg — needed when one test hits a URI twice.
  - **Only** exception: conditions a recording physically can't reproduce — failure injection (retry on 429/5xx, transport errors) and deliberately malformed/out-of-order responses. Keep the mock minimal and comment *why* it can't be VCR.
