# Work in Progress

Progress tracker for building the ingestion pipeline. See [data-ingestion.md](data-ingestion.md) for design.

## Steps

1. **Minimal project skeleton** — `pyproject.toml` + deps, `src/` layout (uv). ✅ Done
2. **Container** — `infra/ingestion/Dockerfile` + `docker-compose.yml`, runs `dagster dev`. Single execution path. Persistent `DAGSTER_HOME` on a named volume. ✅ Done (hello-world asset materializes)
3. **Storage/manifest contract + local-FS store** — `manifest.py` (`ManifestRecord`) + `storage.py` (`RawStore`), JSONL manifest, content-addressed raw files. ✅ Done (idempotency verified via smoke test)
4. **EDGAR client → `raw_filings` Dagster asset** — `edgar.py` (throttled httpx client) + `raw_filings` asset. ✅ Done (fetched 3 Apple 10-Ks, ~1.5 MB each, into raw store + manifest)
5. **VCR.py test** — `tests/test_edgar.py`, one cassette per test (`record_mode="once"`, `filter_headers` strips User-Agent). Covers `recent_filings` + `fetch_document`, replays offline. ✅ Done (both pass, no network)
6. **Retries with exponential backoff** — `_get` in `edgar.py` uses tenacity: retry on 429/5xx + transport errors, exp backoff, 5 attempts, reraise on give-up. Transport seam in `__init__` for testing. `tests/test_edgar_retry.py` (retry-then-succeed, give-up) uses `httpx.MockTransport`. ✅ Done (4 tests pass). No `Retry-After` handling yet — deferred.
7. **Contract acquisition & storyline** — Selected and downloaded 3 Apple material contracts into `data/raw/seed_contracts/AAPL/` and created `docs/contracts-storyline.md` connecting them to Apple 10-K sections for cross-document Q&A (*Governance, Equity Plans & Supply Chain Risk*). ✅ Done
8. **Parsing** — Extracted raw HTML filings into clean Markdown using BeautifulSoup and markdownify, retaining tables per design, with idempotency handled in `ParsedStore`. Added to Dagster asset DAG. ✅ Done

## What the downloaded files are

### 1. 10-K Filings
Each raw file is a **10-K** — a company's mandatory annual report to the SEC (once a year, ~hundreds of pages). We fetched Apple's for FY2025/2024/2023.

Standard 10-K sections (same structure across all companies):
- **Business** — what the company does, products/services.
- **Risk Factors** — everything that could go wrong (competition, supply chain, legal, macro).
- **MD&A** — management explaining in words how the year went and why.
- **Financial Statements** — the core numbers: net sales/revenue, profit, assets, debt, cash.
- **Notes** — fine-print on how the numbers were derived.

Format: **HTML with inline XBRL**. Key numbers are machine-tagged (e.g. `us-gaap:RevenueFromContract...`, `ix:nonNumeric` tags). This gives two uses of the same file:
- **Human text** (business, risk factors) → what RAG retrieves and cites.
- **Tagged XBRL numbers** → exact ground-truth figures to verify answers against (ties to the "reconcile against ground truth" point in [data-ingestion.md](data-ingestion.md)).

### 2. Material Contracts (Exhibit 10s)
Downloaded 3 PDFs into `data/raw/seed_contracts/AAPL/` to ground high-level 10-K disclosures in legal text:
- `320193_000114036126006577_ef20060722_ex10-1.pdf` — **Director Stock Plan (`EX-10.1`)** (Governance / Compensation caps).
- `320193_000114036126006577_ef20065677_ex10-2.pdf` — **Form of RSU Award Agreement (`EX-10.2`)** (Equity vesting / Forfeiture).
- `320193_000110465905058421_a05-20674_1ex10dbd19.pdf` — **Component Purchase Agreement (`EX-10.B.19`)** (Supply chain risk / Supplier remedies).

See [contracts-storyline.md](contracts-storyline.md) for full context, 10-K section pairings, and showcase analyst queries.

## Next session — pick up here

- **Chunking** — implement the Semantic Chunking strategy (defined in `docs/chunking-strategy.md`) to split parsed Markdown into semantic chunks while keeping financial tables completely intact.
- Apple CIK/form stay hardcoded for now — generalizing is not needed yet, revisit only when something requires it.
- Deferred: `Retry-After` header handling on 429s.

## Step 1 — Project skeleton

- Tool: **uv** (`uv init --package`), `src/` layout → importable package `src/financial_doc_ai`.
- Python pinned to **3.12** (`.python-version`); `requires-python = ">=3.12"`.
- Deps: `dagster`, `dagster-webserver`, `httpx` (runtime); `pytest`, `vcrpy`, `ruff` (dev).
- Lockfile `uv.lock` committed for reproducible installs.

## Step 2 — Container (single execution path)

Dev and deploy share one image, so there's no separate host execution path (deliberate — dev == deploy).

- `infra/ingestion/Dockerfile`:
  - Base `python:3.12-slim`; uv binary copied from `docker.io/astral/uv:latest`.
  - Deps installed before app code (`COPY pyproject.toml uv.lock` → `uv sync --frozen --no-install-project`) for layer caching; then `COPY . .` → `uv sync --frozen`.
  - `--frozen` → installs exactly from `uv.lock`.
  - `CMD` runs `dagster dev -h 0.0.0.0 -p 3000`.
- `infra/ingestion/docker-compose.yml`:
  - `build.context: ../..` (repo root, so COPY sees `pyproject`/`src`), `dockerfile:` points back to the Dockerfile.
  - Bind mount `../..:/app` → live code edits without rebuild.
  - Anonymous volume `/app/.venv` → keeps container's Linux venv, unshadowed by host mount.
  - Named volume `dagster_home:/opt/dagster_home` + `DAGSTER_HOME` env → persistent Dagster storage (run/asset history survives restarts). Named volume avoids Windows→Linux bind-mount issues for SQLite.
- Infra layout: per-stack under `infra/<stack>/` (here `ingestion/`); umbrella for future compose stacks + cloud IaC.
- Dagster loads code via `[tool.dagster] module_name = "financial_doc_ai.definitions"` in `pyproject.toml`.
- Run: `docker compose -f infra/ingestion/docker-compose.yml up --build` → UI at `http://localhost:3000`.
- Note: `dagster dev` is a dev server; production splits into `dagster-webserver` + `dagster-daemon` (revisit when adding schedules).

## Manifest contract (step 3)

Acquisition asset outputs per filing: (a) raw bytes at a content-addressed path, (b) a manifest record.

Manifest record fields:
- `natural_id` — source's stable ID (EDGAR: accession number)
- `content_hash` — SHA-256 of raw bytes (idempotency + integrity)
- `source` — `edgar` / `cuad`
- `storage_path` — where raw bytes landed
- `fetched_at` — retrieval timestamp
- `source_metadata` — source-specific dict (EDGAR: CIK, form type, filing date, company)

Principles:
- **Idempotency** — hash bytes; skip if hash already in manifest.
- **Supersession by natural ID, never overwrite** — new version = new record; old records kept as audit evidence.

Manifest storage: **JSONL for now** (simple, no DB); migrate to SQLite/cloud DB later.
