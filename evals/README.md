# Evaluation datasets

Per-stage eval sets for the online path. One JSONL per stage:

- `interpret.jsonl` — `/interpret`: question → `{query_type, filters}` + confirmation gate.
- `retrieval.jsonl` — `search_filings`: question(+filters) → relevant passage (recall@k).
- `answer.jsonl` — `/answer`: retrieved chunks → grounded/cited answer or abstention.

Design, row schema, corpus scope, and the living-dataset workflow are documented in
[../docs/evaluation-strategy.md](../docs/evaluation-strategy.md).

**Status:** datasets only. All `expected` values are assistant-annotated and not yet
human-validated. Eval harnesses and Phoenix experiments are deferred.
