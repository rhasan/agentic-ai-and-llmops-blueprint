# Evaluation Strategy

How we measure whether the online path works, and how the eval sets grow over time.

## Why

We had been hand-testing the same handful of questions after every change to the
chunker, prompts, or model. Those questions are already an eval set — just
uncaptured. Freezing them (a) catches regressions when we touch a stage, and
(b) gives numbers to justify the deferred work (hybrid search, resolver upgrade).
The datasets live in git so they are diffable and reviewed in the same PR as the
change that motivated them.

## Evaluate per component, not just end-to-end

The online (agent) path has separable failure points. A bad end-to-end answer is
useless if you can't tell *which* component broke, so each gets its own dataset,
named after the code it exercises.

| Component | What it checks | Dataset | Metric (later) |
|---|---|---|---|
| `CompanyResolver` + confirm gate | company surface form(s) → `resolved`/`not_found` and whether the gate holds | [`evals/resolver.jsonl`](../evals/resolver.jsonl) | exact-match on `outcomes` / `canonical` / `holds` — deterministic, no LLM judge |
| retrieval (`search_filings`) | question(+filters) → does the relevant passage come back | [`evals/retrieval.jsonl`](../evals/retrieval.jsonl) | recall@k, MRR against an expected section/doc |
| graph retrieval (`graph_search`) | cross-document / multi-hop question → provenance spans multiple filings; entities recovered | [`evals/graph_search.jsonl`](../evals/graph_search.jsonl) | cross-doc recall / entity coverage |
| grounding gate (`serving/grounding.py`) | (answer, passages) → `numbers_grounded` + judge → allow / abstain | [`evals/grounding.jsonl`](../evals/grounding.jsonl) | deterministic number check + LLM-as-judge groundedness |
| agent loop end-to-end (`/agent/ask`) | question → `answered` (grounded + cited) / `abstained` / `held` | [`evals/agent.jsonl`](../evals/agent.jsonl) | outcome-match + citation / abstain-when-absent (LLM-as-judge) |

Sequencing rationale: the resolver and grounding number-check are deterministic
and cheap (highest ROI, no judge cost); retrieval and graph retrieval next; the
end-to-end agent last (fuzziest, needs the judge).

**Renamed from the pre-agent structure.** `interpret.jsonl` → `resolver.jsonl`:
the query-rewrite half of "interpret" (`query_type`/`filters` extraction) no longer
exists, so only company resolution + the confirm gate survive. `answer.jsonl` →
`agent.jsonl`: the deterministic `/answer` generator was replaced by the agent loop
that synthesizes its own answer. `graph_search.jsonl` and `grounding.jsonl` are new,
for the GraphRAG additions.

**Behavioral shift worth noting.** An unresolved company is now **held** by the
confirm gate *before* any search runs — not abstained. Abstention comes only from
the grounding gate (empty retrieval, or an unsupported claim/number). So an
out-of-corpus company (Microsoft) is a `held` row, while an out-of-corpus *year* for
a resolved company (Apple 2019) is an `abstained` row.

## Corpus scope (what "in-corpus" means today)

The live index is **only the 3 Apple 10-Ks (FY2023, FY2024, FY2025)** — every
vector is `company=AAPL`, `doc_type=10-K`, `version=current`. So other companies
(e.g. Microsoft), other document types (the contracts, not embedded yet), and
other years (2019, 2021) are **deliberate out-of-corpus negatives** that test
filter isolation and abstention. As the corpus grows (contracts, more companies),
those rows flip from negative to positive — that is the datasets *evolving*.

## Row schema

One JSON object per line (JSONL). Shared keys:

- `id` — stable, component-prefixed (`res-001`, `retr-001`, `graph-001`,
  `gnd-001`, `agent-001`).
- `task` — `resolver` | `retrieval` | `graph_search` | `grounding` | `agent`.
- `question` — the analyst's question (resolver rows carry `companies` instead;
  grounding rows carry `answer` + `passages`).
- `filters` / `top_k` — retrieval rows carry the filters the search runs on. Agent
  rows don't: the loop picks tools and filters itself from the question alone.
- `tags` — free labels for slicing (`compare`, `out-of-corpus`, `table`,
  `abstention`, `filter-isolation`, …).
- `expected` — the annotation; shape is stage-specific (see the files).
- `notes` — annotation rationale and any assumption to double-check.
- `annotated_by` — provenance. Every row today is `"assistant"`.

Expectations are written **loosely on purpose** where exactness is brittle:
retrieval uses a `section_hint` (substrings expected in a relevant chunk) rather
than a chunk id, because ids change on every re-index; answer uses
`answer_contains_any` rather than a gold paragraph.

## Living-dataset workflow

- Every new interesting query or bug becomes a row, ideally in the PR that fixes it.
- When the corpus or filters change, revisit the out-of-corpus rows (a contract
  row flips to positive once contracts are ingested).
- Keep it small enough to maintain (~10–30 rows/component now) but broad on
  categories (single-fact, compare, table, negative, abstention, held).

## Annotation provenance & validation (open)

Today's `expected` values are **assistant-annotated**, including a few financial
figures (net sales, cost of sales) drawn from knowledge of the filings and
flagged in `notes` for checking. These are not yet human-validated. A future
session covers **how to validate the annotations** (e.g. reconcile figures
against the tagged XBRL ground truth in the filings — see
[data-ingestion.md](data-ingestion.md)).

## Deferred

- **Eval harnesses** — a runner over the JSONL (pytest for the deterministic
  resolver + grounding number checks first, then retrieval recall).
- **Phoenix experiments** — running these datasets as versioned Phoenix
  experiments with traces, since Phoenix is already in the stack
  ([observability.md](observability.md)).
- **LLM-as-judge rubric** for the generation stage.
