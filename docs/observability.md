# Observability

The observability stack for the online path: LLM tracing, latency, token usage, and
request inspection. Prompt versioning is a secondary feature served by the same tool.

## Decision

**Arize Phoenix**, self-hosted as a single container (`infra/observability/`).

| Property | Value |
|---|---|
| Purpose | LLM tracing / observability (primary), prompt versioning (bonus) |
| Deployment | One container, embedded **SQLite** backend, one volume for persistence |
| Ingestion | OpenTelemetry — built-in OTLP collector (gRPC `4317`, HTTP/UI `6006`) |
| Instrumentation | OpenInference auto-instrumentors; traces the LiteLLM → Ollama calls |
| License | **Elastic License 2.0 (ELv2)** — free for internal/reference use; may not be offered as a competing managed service |

Run:
```bash
docker run -p 6006:6006 -p 4317:4317 arizephoenix/phoenix
```

## Why a single container

Prompt versioning is not the driver; **one observability container** is. Phoenix is the
only tool that provides LLM tracing and runs in a single container on an embedded SQLite
backend — no separate Postgres, Clickhouse, Redis, or object store. It fits a 16GB machine
alongside Ollama, and it is teardownable.

Being OpenTelemetry-based means no proprietary SDK: the LiteLLM clients already in the
codebase are instrumented via OpenInference and export spans to Phoenix over OTLP.

## Prompt versioning

Prompts are versioned in Phoenix and fetched at runtime by label.

| Piece | Role |
|---|---|
| `seed/prompts/manifest.toml` | Declares each prompt: logical key → `name`, `label`, `file`. Adding a prompt = one entry + one `.md`. |
| `seed/prompts/*.md` | Canonical seed text. Bootstrap for a fresh Phoenix and the runtime fallback. |
| `seed_prompts.py` | Idempotent, manifest-driven: registers each prompt if absent, tags the version with its label. |
| `prompts.py` | Registry access: `load_manifest()`, `fetch_system_prompt(key)` (fetch the version at the label; fall back to the seed file if Phoenix is unreachable). |
| consumer (`QueryRewriter`) | Fetches its prompt at init and caches it. `system_prompt` injection seam lets tests skip Phoenix. |

Rules:
- **Source of truth is Phoenix** after seeding. The seed file is the bootstrap and fallback, not a live mirror — it goes stale once the prompt is edited in the UI.
- **The label is a movable pointer.** A UI edit creates a new version; moving the `production` label onto it makes it live. The app follows the label; it does not pin a version.
- **Fetch once at init + cache.** A UI change is picked up on the next app start.
- **Config split:** only `PHOENIX_ENDPOINT` is in `.env`; prompt name/label live in the manifest next to the text they describe.

## Alternatives considered

| Tool | Single container? | Why not |
|---|---|---|
| Langfuse v3/v4 | No — 6 services (web, worker, Postgres, Clickhouse, Redis, object store) | Too heavy for the machine |
| Langfuse v2 | Nearly (app + Postgres) | End-of-life; not a base for a new blueprint |
| Langtrace / Laminar | No — require Postgres + Clickhouse | Multi-container |
| SigNoz | No — Clickhouse stack | General APM, not LLM-specific |
| Helicone | Bundles Postgres + Clickhouse + object store | Proxy-based (not OTel); OpenAI/Anthropic-only self-host proxy |
| Traceloop / OpenLLMetry | Not a backend | SDK only — needs a separate backend such as Phoenix |
| MLflow | Yes (SQLite) | Registry/tracking tool, not an observability/tracing tool |
