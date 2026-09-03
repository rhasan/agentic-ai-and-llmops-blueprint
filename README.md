# Agentic AI & LLMOps Blueprint

A production-grade reference implementation of an agentic AI application built
end-to-end with a full LLMOps stack, demonstrating how to build and operate
agentic systems in production.

## Use case

To make the patterns concrete, we use this blueprint to build a Q&A tool for
financial analysts: they ask questions about SEC filings and contracts and get
short answers that quote the exact source passage. Because a wrong answer carries
legal cost, it always cites its source, abstains rather than guesses, and logs
every query for audit.

## Scope

Build one coherent agentic AI application and the complete lifecycle around it:

1. **Agentic AI architecture** — RAG/retrieval, multi-agent design, tool use, an
   agent harness, gateway/model routing.
2. **Storage & infrastructure** — vector stores, structured and immutable storage,
   secrets management.
3. **LLMOps** — CI/CD (GitHub Actions, Docker), eval-in-CI gates, prompt
   versioning, tracing and observability, cost/latency/drift monitoring, and
   reliability patterns.

## Tech Stack

- **LLM / Orchestration:** PydanticAI
- **Cloud:** Azure, Amazon Bedrock
- **Data and Backend:** Chroma, Microsoft GraphRAG with LanceDB, Dagster
- **Serving:** FastAPI, MCP
- **CI/CD:** GitHub Actions, Docker
- **Testing and Evaluation:** pytest, VCR.py, RAGAS, eval-in-CI gates
- **Observability:** Arize Phoenix (single-container, OpenTelemetry), tracing,
  four monitoring signals (cost, latency, drift, quality)

## Quickstart

All development and pipeline execution runs via Docker (`dev == deploy`).

> **Certificate issues?** On Windows behind a TLS-inspecting proxy (e.g. Zscaler),
> run `powershell -ExecutionPolicy Bypass -File infra/ingestion/setup-cert.ps1` once
> before the Docker commands. On any other machine, run the Docker commands
> directly — no setup needed.

### 1. Environment Setup
Copy the example environment file and configure your SEC EDGAR `User-Agent`:
```bash
cp .env.example .env
```
See [.env.example](.env.example) for all configuration options (model provider, credentials, and tuning knobs).

### 2. Run Tests (Offline via VCR)
```bash
docker compose -f infra/ingestion/docker-compose.yml run --rm app uv run pytest
```

### 3. Start Ingestion Pipeline (Dagster)
```bash
docker compose -f infra/ingestion/docker-compose.yml up --build
```
Open [http://localhost:3000](http://localhost:3000) to view the asset graph and materialize `raw_filings`.

### 4. Build the GraphRAG index
Runbook (prompt auto-tune + index build) in [config/graphrag/README.md](config/graphrag/README.md).

### 5. Start the online query path
The serving stack (FastAPI + retrieval MCP server) runs on the shared `llm-net`
network.

## License

TBD.

Third-party note: the observability stack uses **Arize Phoenix**, licensed under the
**Elastic License 2.0 (ELv2)** — free for internal and reference use; may not be offered
as a competing managed service.