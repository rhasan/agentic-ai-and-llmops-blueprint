# Evaluation Strategy

How we measure whether the online path works, and how the eval sets grow over time.

## Why

We had been hand-testing the same handful of questions after every change to the
chunker, prompts, or model. Those questions are already an eval set — just
uncaptured. Freezing them (a) catches regressions when we touch a stage, and
(b) gives numbers to justify the deferred work (hybrid search, resolver upgrade).
The datasets live in git so they are diffable and reviewed in the same PR as the
change that motivated them.

## Evaluate per stage, not just end-to-end

The online path has three separable failure points. A bad end-to-end answer is
useless if you can't tell *which* stage broke, so each gets its own dataset.

| Stage | What it checks | Dataset | Metric (later) |
|---|---|---|---|
| `/interpret` | question → `{query_type, filters}` extraction + confirmation gate | [`evals/interpret.jsonl`](../evals/interpret.jsonl) | exact-match on `query_type` / `proposed_filters` / `needs_confirmation` — deterministic, no LLM judge |
| retrieval (`search_filings`) | question(+filters) → does the relevant passage come back | [`evals/retrieval.jsonl`](../evals/retrieval.jsonl) | recall@k, MRR against an expected section/doc |
| `/answer` | retrieved chunks → grounded, cited answer, or correct abstention | [`evals/answer.jsonl`](../evals/answer.jsonl) | groundedness / citation-correctness / abstain-when-absent (LLM-as-judge) |

Sequencing rationale: `/interpret` is deterministic and cheap (highest ROI, no
judge cost), retrieval next, generation last (fuzziest, needs the judge).

## Corpus scope (what "in-corpus" means today)

The live index is **only the 3 Apple 10-Ks (FY2023, FY2024, FY2025)** — every
vector is `company=AAPL`, `doc_type=10-K`, `version=current`. So other companies
(e.g. Microsoft), other document types (the contracts, not embedded yet), and
other years (2019, 2021) are **deliberate out-of-corpus negatives** that test
filter isolation and abstention. As the corpus grows (contracts, more companies),
those rows flip from negative to positive — that is the datasets *evolving*.

## Row schema

One JSON object per line (JSONL). Shared keys:

- `id` — stable, stage-prefixed (`interp-001`, `retr-001`, `ans-001`).
- `task` — `interpret` | `retrieval` | `answer`.
- `question` — the analyst's question.
- `filters` / `top_k` — retrieval + answer rows carry the *confirmed* filters the
  stage runs on (interpret rows don't; they produce filters).
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
- Keep it small enough to maintain (~10–30 rows/stage now) but broad on
  categories (single-fact, compare, table, negative, abstention).

## Annotation provenance & validation (open)

Today's `expected` values are **assistant-annotated**, including a few financial
figures (net sales, cost of sales) drawn from knowledge of the filings and
flagged in `notes` for checking. These are not yet human-validated. A future
session covers **how to validate the annotations** (e.g. reconcile figures
against the tagged XBRL ground truth in the filings — see
[data-ingestion.md](data-ingestion.md)).

## Deferred

- **Eval harnesses** — a runner over the JSONL (pytest for the deterministic
  interpret checks first, then retrieval recall).
- **Phoenix experiments** — running these datasets as versioned Phoenix
  experiments with traces, since Phoenix is already in the stack
  ([observability.md](observability.md)).
- **LLM-as-judge rubric** for the generation stage.
