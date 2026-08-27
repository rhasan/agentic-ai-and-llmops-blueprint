# Retrieval & Serving (online path)

Design for the next build stage: retrieval over the stamped vector index, exposed
as an **MCP server**, driven by an orchestrator that puts a **human confirmation
gate** in front of the retrieve call. Continues the online path started in
[query-rewrite-strategy.md](query-rewrite-strategy.md).

## Why a confirmation gate

The worst failure mode (see [initial-system-description.md](initial-system-description.md#the-subtle-risk))
is **mis-extraction**: query rewrite picks the wrong company/period, so the answer
is correctly grounded — in the *wrong document*. The grounding check can't catch
this (the answer genuinely matches its wrong source). So the extracted filters are
shown to the analyst to confirm/correct **before** retrieval runs.

## The MCP boundary

Draw MCP at the **tools an agent calls**, not at internal pipeline stages.

- **Retriever → MCP server (build this now).** A `search_filings(query, filters)`
  tool that wraps the vector store: embed the query → metadata-filtered similarity
  search over the stamped fields (`company`/`doc_type`/`period`/`version`) → return
  chunks + citation info. Any host (our orchestrator, Claude Desktop, an agent
  harness) can call it. Building retrieval *as* an MCP server is the pattern we want
  to show.
- **Orchestrator → MCP client/host.** Runs `interpret` → (confirmation gate) → calls
  the `search_filings` tool over MCP → generate → ground. The HITL gate lives here,
  client-side, before the tool call. The tool stays dumb: filters in, chunks out.
- **Stays internal (not MCP):** query rewrite and the company resolver — pipeline
  stages, not reusable tools. Keep as library code.
- **Future MCP candidates (not now):** a ground-truth/XBRL **figures** tool for the
  grounding step (exact-number verification), and a citation/passage **fetch** tool.

## The HITL gate — kept simple

Stateless, two calls. No server-side session state / checkpointer yet.

1. `interpret(question)` → proposed filters + per-company resolution outcomes.
2. `answer(question, confirmed_filters)` → retrieve (MCP) → generate → ground.

The client renders the proposed filters, the user edits them, and sends them back
to `answer`. Add durable/resumable state (e.g. LangGraph interrupt + checkpointer)
later only if a real multi-turn UI needs it — not required to demonstrate the gate.

Always surface the filters; require an explicit confirm when signals are weak
(ambiguous/fuzzy resolution, low extraction confidence, multi-company `compare`).

## Entry point (no web UI yet)

A thin FastAPI in the serving stack (its Dockerfile already targets
`financial_doc_ai.api:app`) with two endpoints — `POST /interpret`, `POST /answer` —
enough to exercise the flow. A browser UI is later polish, low priority.

## Next build (concrete)

1. `search_filings` **MCP server** wrapping `VectorStore` (+ query embedding).
2. Minimal **orchestrator** (MCP client) doing interpret → gate → search → (answer).
3. Thin **FastAPI** entry point exposing the two-call flow.

Deferred: company resolver upgrade (low priority), generation + grounding + audit
log, ground-truth figures MCP tool, durable HITL state, web UI.
