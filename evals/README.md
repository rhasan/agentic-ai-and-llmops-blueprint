# Evaluation datasets

Per-component eval sets for the online (agent) path. One JSONL per component, named
after the code it exercises:

- `resolver.jsonl` — `CompanyResolver` + the agent's confirm gate: company surface
  form(s) → `resolved`/`not_found` and whether the gate holds. Deterministic.
- `retrieval.jsonl` — `search_filings` (vector): question(+filters) → relevant
  passage (recall@k).
- `graph_search.jsonl` — `graph_search` (DRIFT graph): cross-document / multi-hop
  question → provenance spans multiple filings / entities recovered.
- `grounding.jsonl` — the post-loop grounding gate (`serving/grounding.py`):
  (cited blocks, passages keyed by `chunk_id`) → a verdict per block → gate outcome
  `allow` / `resynthesize` / `abstain`. Each block is checked against **only the
  passages it cites**, cheapest check first: cited id was actually retrieved →
  figures appear verbatim → LLM judge. Rows tagged `deterministic` need no model
  call at all.
- `agent.jsonl` — the agent loop end-to-end (`/agent/ask`): question → `answered`
  (grounded + cited) / `abstained` (grounding gate) / `held` (confirm gate).

Renamed from the pre-agent structure: `interpret.jsonl` → `resolver.jsonl` (the
query-rewrite half of "interpret" is gone; only company resolution + the confirm
gate survive), and `answer.jsonl` → `agent.jsonl` (the deterministic `/answer`
generator was replaced by the agent loop). `graph_search.jsonl` and
`grounding.jsonl` cover the GraphRAG additions.

**Behavior note.** An unresolved company (e.g. Microsoft, Tesla) is now **held** by
the confirm gate *before* any search runs — it is not an abstention. Abstention
comes only from the grounding gate: empty retrieval, or an unsupported claim/number.

Design, row schema, corpus scope, and the living-dataset workflow are documented in
[../docs/evaluation-strategy.md](../docs/evaluation-strategy.md).

**Status:** datasets only. All `expected` values are assistant-annotated and not yet
human-validated. Eval harnesses and Phoenix experiments are deferred.
