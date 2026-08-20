# Agentic AI & LLMOps Blueprint

A production-grade reference implementation of an agentic AI application built
end-to-end with a full LLMOps stack, demonstrating how to build and operate
agentic systems in production.

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

- **LLM / Orchestration:** Azure OpenAI, LangChain / LangGraph
- **Cloud:** Azure, AWS
- **CI/CD:** GitHub Actions, Docker
- **Evaluation:** RAGAS, VCR.py, eval-in-CI gates
- **Observability:** Langfuse, tracing, four monitoring signals
  (cost, latency, drift, quality)

## Quickstart

All development and pipeline execution runs via Docker (`dev == deploy`).

### 1. Environment Setup
Copy the example environment file and configure your SEC EDGAR `User-Agent`:
```bash
cp .env.example .env
```

### 2. Run Tests (Offline via VCR)
```bash
docker compose -f infra/ingestion/docker-compose.yml run --rm app uv run pytest
```

### 3. Start Ingestion Pipeline (Dagster)
```bash
docker compose -f infra/ingestion/docker-compose.yml up --build
```
Open [http://localhost:3000](http://localhost:3000) to view the asset graph and materialize `raw_filings`.

## License

TBD