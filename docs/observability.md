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
| Instrumentation | PydanticAI's **native** OTel emission for the agent loop, plus the OpenInference LiteLLM instrumentor for the retrieval and GraphRAG model calls. Both switched on in `telemetry.py`. See *Tracing* below. |
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

## Tracing

1. **Instrument the app** — point OpenTelemetry at Phoenix from the serving process.
   PydanticAI emits the spans: the agent run, each model turn with its token counts,
   each tool call. **Done.**
2. **Instrument the MCP servers** — the same setup in each server, plus a LiteLLM
   instrumentor for the model calls they make. The MCP SDK propagates the trace id, so
   one question is one trace across all three containers. **Done.**
3. **Read cost and latency in Phoenix** — token spend per model and time spent per
   step, from the spans the first two steps produce. Dashboard work, no new
   instrumentation.

Postponed: decision traces (grounding gate, rewriter, confirm gate, retrieval, DRIFT) —
they go with the audit log. Also the eval harness and the quality/drift signals.

Size: 1–2 sessions.

### Step 1 — the concept

Three ideas:

- **A span** is a timed, named record of one operation with attributes — *"model call,
  3.1s, 1,800 tokens"*. Nested spans form the trace of one request.
- **A provider** collects spans in the process and ships them somewhere. The serving
  process has none, so anything emitting spans today is talking to a no-op. Step 1
  creates one and points it at Phoenix.
- **The emission is already written.** PydanticAI knows how to describe its own agent
  runs, model calls and tool calls as spans; it only needs switching on. We don't author
  spans — we enable a library's.

Two constraints shape the implementation: export stays off the request path, and Phoenix
being unreachable must not break answering.

One setup function, called once when the process starts.

### Step 1 — implementation

| Piece | Role |
|---|---|
| `arize-phoenix-otel` | Dependency. Supplies the tracer provider, batch processor and OTLP exporter with Phoenix's defaults — either as one `register()` call or as drop-in pieces. |
| `telemetry.py` (top-level) | `setup_tracing(project_name)`: return early if `PHOENIX_ENDPOINT` is unset; otherwise build the provider, set it as the global one, and call `Agent.instrument_all(InstrumentationSettings(tracer_provider=...))`. Top-level because step 2 reuses it. |
| `serving/api.py` | A FastAPI `lifespan` calling `setup_tracing("online")` — once per process, before the agent is built. The project is the whole online path, not this one container, so the MCP servers join the same trace in step 2. |

Three things the implementation turns on:

- **The collector is a path, not the base URL.** `PHOENIX_ENDPOINT` is the server's base
  URL, which is what the prompt client wants. OTLP lives at `/v1/traces` on it. Pass the
  base alone and the exporter posts to `/`, Phoenix answers **405**, and spans are
  produced and silently dropped. `telemetry.py` appends the path.
- **Batch, not simple, processing.** A `SimpleSpanProcessor` exports each span inline as
  it ends — on the request path.
- **The provider is set globally.** The MCP SDK's own spans, the ones that carry the
  trace across the transport, are written against whatever provider is global.
- **Failure is swallowed.** Setup is wrapped; a failure logs a warning and the app serves
  untraced. Same rule as the prompt registry's seed-file fallback.

What one `/agent/ask` produced, verified 2026-10-04: **14 spans** — `invoke_agent agent`,
`invoke_agent judge`, three `chat gpt-5.4-mini`, `execute_tool search_filings`, and the
MCP protocol spans. Every LLM span carries `gen_ai.usage.input_tokens` /
`output_tokens`, and an `operation.cost` figure PydanticAI computes itself.

### Step 2 — the concept

- **A provider is per process.** Step 1's provider sits in the serving container. It
  cannot reach the MCP servers, so each server calls the same `setup_tracing`.
- **The trace already crosses the boundary.** The MCP client puts the trace id in every
  request it sends. Each server has middleware, on by default, that reads it and attaches
  its span to the parent. Those spans exist today and are thrown away, because no
  provider collects them. Nothing to plumb.
- **One project, one tree.** Phoenix sets the project per exporter, and a span appears
  under its parent only inside the same project. So every process on the online path
  exports to one project, `online`. Ingestion takes its own later.
- **The model calls inside the servers are invisible.** Nothing records the query
  embedding or the DRIFT calls, so the tokens and costs in Phoenix are the serving
  process alone. Both servers call their models through LiteLLM, so one instrumentor on
  that one library covers both.

One setup call per server, one LiteLLM instrumentor, one project rename. The result is a
single trace per question across three containers.

### Step 2 — implementation

| Piece | Role |
|---|---|
| `openinference-instrumentation-litellm` | Dependency. Instruments LiteLLM's entry points — `completion`, `acompletion`, `CreateEmbeddings` — which is what `Embedder` and GraphRAG's `graphrag_llm` call. |
| `telemetry.py` | One added line: `LiteLLMInstrumentor().instrument(tracer_provider=provider)`. A no-op in processes that don't use LiteLLM. |
| `retrieval/server.py`, `graph_retrieval/server.py` | `setup_tracing("online")` in `__main__`, before `mcp.run(...)`. |

Two things worth knowing:

- **Don't use LiteLLM's own `callbacks = ["otel"]`.** It propagates and nests correctly,
  but every call — chat and embedding alike — arrives as a span named
  `raw_gen_ai_request` carrying raw request dumps (`llm.azure.messages`,
  `llm.None.model`) and no usable token attributes. Tokens are the whole point, so the
  instrumentor replaces it.
- **Rebuild the MCP images, not just the code.** Their Dockerfiles install the same
  `pyproject.toml`; the repo is bind-mounted but the dependency isn't.

Verified 2026-10-04, one graph question → **one trace, 89 spans, three containers**:

```
invoke_agent agent
  invoke_agent judge → chat gpt-5.4-mini
  chat gpt-5.4-mini
  execute_tool graph_search
    tools/call graph_search
      MCP send tools/call graph_search
        tools/call graph_search          ← graph-retrieval container
          acompletion × 26               ← DRIFT's model calls
          CreateEmbeddings × 21
```

Of that question's 104,474 tokens, the ~20,000 below the MCP boundary — 26 DRIFT
completions and 21 embeddings — were invisible before this step. The cost that follows
from them is step 3.

### Step 3 — cost and latency

| Signal | Where it comes from |
|---|---|
| **Cost** | Phoenix prices each span itself, from the token counts and the model name |
| **Latency** | Span durations — the agent run for the total, `execute_tool graph_search` for what DRIFT costs, the judge for what the gate adds |

Quality and drift need a known-good baseline to compare against, which is the eval
harness. Postponed with it.

**Cost is Phoenix's job, not ours.** It ships a price table of ~200 models and multiplies
it by each span's tokens. `gpt-5.4-mini` is in it, and DRIFT's spans price correctly even
though they name the model `azure/gpt-5.4-mini`. Two things had to be fixed for
embeddings, though:

- **No embedding model carries a price.** Added via Phoenix's GraphQL `createModel`:
  `text-embedding-3-small`, `$0.02` per million input tokens, output `0.0` (Phoenix
  rejects an entry without an output price). The figure comes from LiteLLM's own price
  map, `azure/text-embedding-3-small → input_cost_per_token: 2e-08`.
- **Phoenix couldn't find the model to price.** It matches on `llm.model_name`, and
  OpenInference's embedding spans record the model under `embedding.model_name`. The
  mismatch was silent: tokens shown, cost zero, whatever price was configured.
  `telemetry.py` wraps the span exporter and copies the name across. Spans are immutable
  once ended, so it re-emits a copy; everything else passes through.

With both in place, every model call in a trace is priced. One graph question, verified
2026-10-04:

| | calls | tokens | cost |
|---|---|---|---|
| serving — `chat gpt-5.4-mini` | 16 | 84,517 | $0.069249 |
| graph container — `acompletion` | 26 | 18,546 | $0.029075 |
| embeddings — `CreateEmbeddings` | 21 | 1,411 | $0.000028 |
| **total** | | | **$0.098352** |

Embeddings are 0.03% of the bill. That they are negligible is a thing worth *knowing*
rather than assuming, which is the argument for pricing them at all. Note Phoenix rounds
cost to six decimals in its summary views, so a single 3-token embedding reads as zero
there while carrying a real `llm.cost.total` of `6e-08`.

### Open decision

**`include_content`.** `InstrumentationSettings` defaults to sending prompt and response
**text** to Phoenix, so filing passages and answers land in the trace store. Fine for a
local blueprint; for a regulated deployment it is a decision, not a default — so set it
explicitly and say why. Currently left at the default.

### Traces are not the audit log

[initial-system-description.md](initial-system-description.md) requires an **immutable
7-year audit record per query, written synchronously — if the audit write fails, the
request fails**. Phoenix traces are *not* that: they are sampled-by-default,
retention-bounded, and best-effort by design. The audit log is a separate, still-unbuilt
piece of work. Don't let one look like the other.

## Prompt versioning

Prompts are versioned in Phoenix and fetched at runtime by label.

| Piece | Role |
|---|---|
| `seed/prompts/manifest.toml` | Declares each prompt: logical key → `name`, `label`, `file`. Adding a prompt = one entry + one `.md`. |
| `seed/prompts/*.md` | Canonical seed text. Bootstrap for a fresh Phoenix and the runtime fallback. |
| `prompts/seed.py` | **Push** (bootstrap): idempotent, manifest-driven — registers each prompt *if absent* and tags the version with its label. Skips anything already in Phoenix, so it never overwrites a UI edit. |
| `prompts/pull.py` | **Pull** (sync back): reads the version at each label and writes it over the seed file. Run after a UI edit so the fallback stops being stale and the change lands in git. |
| `prompts/registry.py` | Registry access: `load_manifest()`, `fetch_system_prompt(key)` (fetch the version at the label; fall back to the seed file if Phoenix is unreachable). |
| consumers (agent, grounding judge, synthesis) | Fetch the prompt at build time. Each has an `instructions` injection seam so tests skip Phoenix. |

Rules:
- **Source of truth is Phoenix** after seeding. The seed files are the bootstrap and the runtime fallback.
- **The label is a movable pointer.** A UI edit creates a new version; moving the `production` label onto it makes it live. The app follows the label; it does not pin a version.
- **Fetch once at build + cache.** A UI change is picked up on the next app start (or container recreate).
- **Config split:** only `PHOENIX_ENDPOINT` is in `.env`; prompt name/label live in the manifest next to the text they describe.

### Keeping the seed files in sync

The seed files are not a live mirror, and a stale one is quietly dangerous: if Phoenix
is unreachable the app keeps serving, using the old text from disk. So after editing a
prompt in the UI, pull it back down:

```bash
docker compose -f infra/serving/docker-compose.yml run --rm --no-deps -T app \
    uv run python -m financial_doc_ai.prompts.pull
git diff seed/prompts/     # shows exactly what changed in the UI
```

Then commit, so prompt changes are reviewable like any other change.

```
  edit in Phoenix UI  ──→  pull  ──→  git diff  ──→  commit
  (Phoenix wins)                                     (fallback + history stay honest)
```

The two directions are deliberately asymmetric: `seed` only ever *creates*, so it
cannot clobber a UI edit; `pull` is the only thing that writes to the files. A prompt
added in git reaches Phoenix via `seed`; a prompt changed in the UI reaches git via
`pull`.

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
