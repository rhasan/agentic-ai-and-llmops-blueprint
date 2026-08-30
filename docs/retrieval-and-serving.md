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

A thin FastAPI in the serving stack (`financial_doc_ai.serving.api:app`) with two
endpoints — `POST /interpret`, `POST /answer` — enough to exercise the flow. A
browser UI is later polish, low priority.

## Async: the online path is async end to end

`interpret` and `answer` both wait on slow calls — `interpret` on the query-rewrite
LLM, `answer` on the retrieval MCP tool. Under many concurrent users those waits
would exhaust FastAPI's capped sync threadpool and queue requests, so the whole
path is `async` (rewriter → pipeline → orchestrator → routes) and the worker is
free to serve others during each wait. The company resolver stays sync — a fast
in-memory lookup, called without `await`; make it async only if it grows a slow
step. Rationale and the plain-language version: [async-vs-sync.md](async-vs-sync.md).

## Build status

1. ✅ `search_filings` **MCP server** wrapping `VectorStore` (+ query embedding).
2. ✅ Minimal **orchestrator** (MCP client) doing interpret → gate → search.
3. ✅ Thin **FastAPI** entry point exposing the two-call flow (async).
4. ✅ **Generation** — `AnswerGenerator` (`serving/generator.py`) drafts a cited
   answer over the retrieved chunks: numbered `[n]` citations mapped back to results
   by position, plus a `can_answer` abstention flag.

Next: **two answer-quality guards + audit log**. These catch *different* failures —
don't conflate them:
- **Guard 1 — answerability/relevance:** catches retrieval surfacing the wrong
  passages (faithful answer to an irrelevant chunk — "right document, wrong
  passage"). Lever: sharpen `can_answer` into a relevance gate + optional retrieval
  **distance floor** so weak hits abstain before generation. Cheap; do first.
- **Guard 2 — faithfulness/grounding:** catches invented/misstated content vs. the
  sources (LLM grader for prose + exact-match for numbers, pass→return / fail→
  abstain). A number/claim-integrity check — NOT a retrieval-quality net.
- **Audit log:** synchronous immutable write of the full turn (question, confirmed
  filters, retrieved chunk ids, answer, citations, can_answer, both guard verdicts).

Deferred: company resolver upgrade (low priority), ground-truth figures MCP tool,
durable HITL state, web UI.
