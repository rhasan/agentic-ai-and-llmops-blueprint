# Query Rewrite Strategy

The first stage of the online (hot) query path. Takes the analyst's question plus
session context and produces two things: a self-contained natural-language query for
retrieval, and a set of structured metadata filters. It is filter *extraction*, **not**
a query-type classifier — answer synthesis is left to the generator LLM.

See the full design in
[w7-financial-doc-analysis-design.md](refs/systems/sys-a/w7sysa/w7-financial-doc-analysis-design.md)
(Step 2, Step 3). Online path order: **query rewrite → retrieve → generate → grounding → audit.**

## Where this sits in the build

Sequenced as: **query rewrite → modify ingestion to stamp filter metadata → retrieval.**
Query rewrite defines which filter fields exist, so it defines what the ingestion step
must stamp on each chunk, so retrieval can then filter on real metadata. Demand-driven —
each step defines the contract for the next.

## Input / Output

**Input:** the current question + session/conversation context (so follow-ups like
"compare to last year's filing" resolve to a standalone query).

**Output:** `{ query_type, rewritten_query, filters }`.

### `query_type`
An explicit intent label. Only one type earns its own place, because it is the only one
that needs different downstream logic:

| Type | Meaning |
|---|---|
| `compare` | the analyst wants the same topic contrasted across multiple scopes (companies or periods) |
| `other` | everything else — single-fact lookup, cross-document reconciliation, follow-ups, etc. |


### `rewritten_query`
A single self-contained natural-language question, with follow-ups resolved against
session context. **Retains** the company/period words (e.g. "How did Apple's revenue
change in fiscal 2024?"). This is the text that gets embedded for the similarity search.

- Decision: keep scope words in the query (do **not** strip them into filters only).
  Rationale: a self-contained question is more readable and makes a cleaner audit record —
  the logged query text stands alone without needing the filters to interpret it.
- The scope words also influence the embedding; harmless, since the metadata filter
  already enforces scope.

### `filters`
Structured constraints for metadata-filtered retrieval. `company`, `doc_type`, and
`period` share one shape: optional, list-capable, `None` = unconstrained. `version` is
the exception — it defaults to `current`.

| Field | Type | Values / notes | "Not found" |
|---|---|---|---|
| `company` | list of strings | canonical id — ticker (`AAPL`), mapped from name. List → compare questions span companies. | `None` → no company constraint |
| `doc_type` | list of strings | `10-K`, `10-Q`, `8-K`, `contract` (our corpus: `10-K`, `contract`). Optional narrowing filter; list → cross-document questions span types. | `None` → all doc types |
| `period` | list of strings | fiscal year `"2024"`; list for compare/trend questions | `None` → no period constraint |
| `version` | enum | `current` (default) / `superseded` / specific | defaults to `current` |

**"No filters found"** = all fields `None`/default → an unconstrained similarity search.
Query rewrite does **not** abstain on this; the mis-extraction mitigation handles it.

## Design notes

- **doc_type is a narrowing filter, not routing.** Default `None` searches all types.
  Absent far more often than present. A single value would break cross-document Q&A (e.g.
  "does the RSU award agreement match what the 10-K discloses about equity plans?" needs
  both `10-K` and `contract`), so it is list-capable.
- **Compare questions → per-entity retrieval.** `company`/`period` as lists become
  *separate* retrievals (one per scope) so one scope's chunks don't crowd out another's,
  rather than OR-ing them into a single search.
- **Mis-extraction is the top risk** (design Step 5, #1, "Very high"). Wrong company/period →
  answer grounded in the *wrong* document; the grounding check can't catch it. Mitigation
  is not silent abstention — it's showing the extracted filters to the analyst for
  verification. Query rewrite's accuracy is what that mitigation depends on.
- **Model tier:** small — the task is mechanical (question + context → query + filters).

## Company resolver

Analysts type free text — "Apple", "Apple Inc", misspellings, many forms. The `company`
filter must be a canonical id, and we can only answer about companies actually in the
corpus. So resolution is a **separate deterministic resolver**, not part of the LLM call:
query rewrite extracts the *surface form* the analyst wrote; the resolver maps it to the
canonical id. The LLM proposes, the registry decides. Keeping it deterministic isolates
the testable part from the LLM and scales past what fits in a prompt.

**Registry (the resolver's dependency, not its input):** loaded internally from the
ingested-corpus metadata. EDGAR hands us the canonical triple at ingest — CIK + ticker +
official company name (`company_tickers.json`) — so the registry is a byproduct of
ingestion, not a separately maintained thing. This is *why* the company key is stamped on
chunks (see Open items → ingestion metadata). For the current corpus the registry has one
entry (Apple); the mechanism is what we're showing, not the scale.

**Input:** a list of surface-form strings (list, because compare questions yield several,
e.g. `["Apple Inc", "microsft"]`). Each element resolved independently.

**Output:** one result per input surface form. Three outcomes — resolution can succeed,
fail, or be ambiguous, and each drives a different downstream action:

| Outcome | Contains | Downstream action |
|---|---|---|
| `resolved` | canonical id (`AAPL`), official name, CIK, match type (`exact` / `alias` / `fuzzy`) | use as the `company` filter |
| `not_found` | the original surface form, no match | tell analyst "we don't have that company" — don't search blindly |
| `ambiguous` | the surface form + list of candidate matches | surface candidates to analyst to disambiguate |

Per-element shape:
`{ input, outcome, canonical?: {ticker, name, cik}, match_type?, candidates?: [...] }`.

Notes:
- **Match type is carried through** so a low-confidence `fuzzy` match can still be flagged
  to the analyst even when it "resolved" — feeds the mis-extraction mitigation.
- **`not_found` is a first-class outcome**, not an exception — the clean signal that the
  question is about a company outside the corpus (catches mis-extraction early).
- **Scope: company only.** `period` ("last year" → `2024`) and `doc_type` ("annual report"
  → `10-K`) also need normalization, but those are simpler and separate — not this
  component.

**Status:** a dummy implementation exists (`query/resolver.py` `CompanyResolver`) — exact
lookup against a hardcoded Apple registry, returning the contract above (`match_type` always
`exact`, no alias/fuzzy/`ambiguous` yet). It is called on the rewrite output in
`pipeline.py` (`QueryPipeline`: rewrite → resolve `filters.company`).

The registry data now exists: the ingestion-metadata step fetches SEC's
`company_tickers.json` into `data/reference/company_tickers.json` (`CompanyRegistry`,
cik↔ticker↔name), and chunks are stamped with the canonical `company` ticker. The
remaining work is to point the resolver at that registry and add alias/fuzzy matching +
`ambiguous` outcomes, replacing the hardcoded Apple dict.

## Implementation

- **Code:** `src/financial_doc_ai/query/rewriter.py` — `QueryRewriter`, a thin LiteLLM
  `completion()` wrapper (dumb client). Output typed as Pydantic `QueryRewrite` (+ nested
  `Filters`); filled via `response_format=QueryRewrite`. System prompt enforces
  explicit-only filter extraction and the narrow `compare` definition.
- **Model:** `qwen2.5:3b-instruct` via Ollama (`QUERY_REWRITE_MODEL`), api base
  `LLM_API_BASE`. Provider-agnostic; Azure OpenAI later via config only.
- **Infra:** shared `llm-net` Docker network. `infra/ollama/` owns Ollama and the model
  pulls (`nomic-embed-text` + chat model). `infra/serving/` is the online-path stack (own
  Dockerfile). Both attach to `llm-net` and reach Ollama at `http://ollama:11434`.
- **Test:** `tests/test_query_rewriter.py` — VCR cassettes record the real LiteLLM→Ollama
  call once, replay offline. Covers the `other` and `compare` cases.

## Open items

- **Company representation** — ✅ resolved: canonical id is the **ticker** (`AAPL`), with
  CIK and official name carried alongside (see Company resolver). Must match whatever the
  ingestion step stamps on each chunk.
- **Session context handling** — how a session is represented, how many turns are kept,
  and whether/how older turns are compacted. The design says session context is an input
  but never specifies the mechanism. Deferred.
- **Ingestion metadata** — ✅ done. Chunks are stamped with `company`/`doc_type`/`period`/
  `version` at embed time (`metadata.py` `chunk_filter_fields`), driven by
  `config/companies.toml` + `CompanyRegistry`. Unblocks the real resolver and
  metadata-filtered retrieval.
