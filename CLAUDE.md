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
- `docs/data-ingestion.md` — data sources (EDGAR + CUAD) and the ingestion architecture decisions.
- `docs/work-in-progress.md` — **the live progress tracker.** Read this first to see where the build is and what's next.

## Stack & layout

- **Package:** `src/financial_doc_ai/` (uv, Python 3.12).
- **Orchestrator:** Dagster (offline/batch ingestion pipeline). Runs only inside the container.
- **Execution path:** everything runs in Docker (dev == deploy). Compose stack per subsystem under `infra/<stack>/` — currently `infra/ingestion/`.
  - Run: `docker compose -f infra/ingestion/docker-compose.yml up --build` → Dagster UI at `http://localhost:3000`.
- **Storage:** local FS now (`data/`, gitignored), JSONL manifest; migrate to cloud (Blob) + SQLite/DB later via the storage seam.

## Conventions

- Storage goes through `RawStore` (`src/financial_doc_ai/storage.py`): content-addressed raw bytes + append-only JSONL manifest; idempotent by content hash; never overwrite (old versions are audit evidence).
- External clients (e.g. `edgar.py`) stay "dumb" — fetch only, no storage logic. Storage lives in `RawStore`.
- `EDGAR_USER_AGENT` comes from `.env` (see `.env.example`), injected into the container by compose.
