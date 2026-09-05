"""Graph retrieval core: a DRIFT search over the GraphRAG index.

The graph-side analogue of retrieval/search.py. It runs GraphRAG's DRIFT search
(the method that merges local + global) through the same model config the offline
index was built with, then returns the SAME shapes the vector side produces — a
generated sub-answer PLUS the passages it drew on — so a later fusion step can
combine sources uniformly and dedup citations by our chunk id.

The one subtlety is provenance. DRIFT's context tables label each passage with a
per-sub-query ordinal (`short_id`), NOT our chunk id, so citing with it would
match nothing. We recover the real chunk id by joining that ordinal back through
the text_units table: `sources.id` (== `human_readable_id`) -> `document_id`,
which IS our chunk id ("{natural_id}:{chunk_index}"). From there we id-join to the
chunk store for the citation fields, exactly as the vector store's stamped
metadata would give. See docs/specs/graphrag-financial-doc-ai.md (Fusion).

graphrag is a heavy dependency (LanceDB, the whole index pipeline), so it lives
only in this subpackage / its MCP service — never in the serving container.
"""

import json
from pathlib import Path

import pandas as pd
from graphrag.api import drift_search
from graphrag.config.load_config import load_config
from pydantic import BaseModel

from financial_doc_ai.ingestion.graph_indexer import (
    GRAPHRAG_ROOT,
    _configure_models,
    preserve_cwd,
)
from financial_doc_ai.retrieval.search import Citation, SearchResult
from financial_doc_ai.serving.generator import GeneratedAnswer
from financial_doc_ai.storage import ChunkStore

DATA_ROOT = Path("/app/data")
OUTPUT_DIR = "/app/data/graphrag/output"  # the index parquets build_graph_index wrote

# GraphRAG CLI defaults; reasonable constants, not worth exposing as knobs yet.
_COMMUNITY_LEVEL = 2
_RESPONSE_TYPE = "Multiple Paragraphs"

# The index parquets DRIFT needs loaded (mirrors the CLI's query loader).
_INDEX_TABLES = (
    "entities",
    "communities",
    "community_reports",
    "text_units",
    "relationships",
)


class GraphAnswer(BaseModel):
    """A graph sub-answer plus the passages it was built from.

    Symmetric with the vector side (GeneratedAnswer over a list of SearchResult),
    so fusion can treat both sources the same. DRIFT already writes a cited prose
    answer, so `sub_answer` wraps that directly; `results` carry our chunk ids for
    dedup/attribution.
    """

    sub_answer: GeneratedAnswer
    results: list[SearchResult]


def _load_chunk_index(chunk_store: ChunkStore) -> dict[str, dict]:
    """Build a {chunk_id -> citation fields + text} lookup from the chunk store.

    chunk_id = "{natural_id}:{chunk_index}" — the same key GraphRAG carries as a
    text_unit's document_id. The document-level `metadata` block holds the four
    filter fields (company/doc_type/period/version); chunk-level attrs (headers,
    chunk_index) live on each chunk. Same manifest traversal as build_documents_df.
    """
    index: dict[str, dict] = {}
    if not chunk_store.manifest_path.exists():
        return index
    with chunk_store.manifest_path.open() as f:
        for line in f:
            rec = json.loads(line)
            payload = json.loads(
                (chunk_store.root / rec["storage_path"]).read_text(encoding="utf-8")
            )
            nid = payload["natural_id"]
            md = payload.get("metadata", {})
            for c in payload["chunks"]:
                index[f"{nid}:{c['chunk_index']}"] = {
                    "natural_id": nid,
                    "chunk_index": c["chunk_index"],
                    "text": c["text"],
                    "headers": c.get("headers", {}),
                    "company": md.get("company"),
                    "doc_type": md.get("doc_type"),
                    "period": md.get("period"),
                    "version": md.get("version"),
                }
    return index


def _iter_sources_frames(context_data):
    """Yield every `sources` DataFrame in DRIFT's context_data.

    The `drift_search` API returns a flat reduced context — {"entities": df,
    "sources": df} — so `sources` is a top-level key. We also tolerate the
    per-sub-query nested form ({sub_query: {"sources": df}}) that other search
    methods / older versions emit, so the recovery survives either shape.
    """
    if not isinstance(context_data, dict):
        return
    direct = context_data.get("sources")
    if isinstance(direct, pd.DataFrame):
        yield direct
    for value in context_data.values():
        if isinstance(value, dict) and isinstance(value.get("sources"), pd.DataFrame):
            yield value["sources"]


def recover_passages(
    context_data,
    hrid_to_chunk_id: dict,
    chunk_index: dict[str, dict],
    top_k: int,
) -> list[SearchResult]:
    """Recover our chunk ids from DRIFT's `sources` table(s) and id-join.

    Pure (no models/parquets), so the provenance recovery — the one subtle part —
    is unit-testable on its own. The `sources.id` column holds short_ids
    (== human_readable_id, as strings), which we map to our chunk id and then to
    the stored citation fields. Deduped across tables, capped at top_k.
    """
    seen: set[str] = set()
    results: list[SearchResult] = []
    for sources in _iter_sources_frames(context_data):
        if sources.empty or "id" not in sources:
            continue
        for short_id in sources["id"]:
            try:
                chunk_id = hrid_to_chunk_id.get(int(short_id))
            except (TypeError, ValueError):
                chunk_id = None
            if not chunk_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            fields = chunk_index.get(chunk_id)
            if fields is None:
                continue  # graph references a chunk not in the store; skip
            results.append(
                SearchResult(
                    text=fields["text"],
                    distance=None,
                    source="graphrag",
                    citation=Citation(
                        natural_id=fields["natural_id"],
                        company=fields["company"],
                        doc_type=fields["doc_type"],
                        period=fields["period"],
                        version=fields["version"],
                        chunk_index=fields["chunk_index"],
                        headers=fields["headers"],
                    ),
                )
            )
            if len(results) >= top_k:
                return results
    return results


class GraphSearch:
    def __init__(
        self,
        chunk_store: ChunkStore | None = None,
        output_dir: str | None = None,
    ) -> None:
        self.chunk_store = chunk_store if chunk_store is not None else ChunkStore(DATA_ROOT)
        self.output_dir = Path(output_dir or OUTPUT_DIR)

        # Load the index tables + config once (built once at server import). Model
        # wiring is reused from the indexer so provider/dim switch from the same
        # .env, and DRIFT's embedding store dim matches the built vectors.
        self._tables = {
            name: pd.read_parquet(self.output_dir / f"{name}.parquet")
            for name in _INDEX_TABLES
        }
        # load_config chdirs to root_dir; restore it right after (drift reads no
        # relative paths — prompts default to built-ins, storage is absolute).
        with preserve_cwd():
            self.config = load_config(root_dir=Path(GRAPHRAG_ROOT))
            _configure_models(self.config)

        # short_id (== human_readable_id) -> our chunk id, for provenance recovery.
        text_units = self._tables["text_units"]
        self._hrid_to_chunk_id = dict(
            zip(text_units["human_readable_id"], text_units["document_id"], strict=True)
        )
        self._chunk_index = _load_chunk_index(self.chunk_store)

    async def search(self, query: str, top_k: int = 10) -> GraphAnswer:
        response, context_data = await drift_search(
            config=self.config,
            entities=self._tables["entities"],
            communities=self._tables["communities"],
            community_reports=self._tables["community_reports"],
            text_units=self._tables["text_units"],
            relationships=self._tables["relationships"],
            community_level=_COMMUNITY_LEVEL,
            response_type=_RESPONSE_TYPE,
            query=query,
        )
        results = recover_passages(
            context_data, self._hrid_to_chunk_id, self._chunk_index, top_k
        )
        answer = str(response).strip()
        sub_answer = GeneratedAnswer(
            answer=answer or "The graph search returned no answer.",
            citations=[],  # fusion re-cites across sources; not our job here
            can_answer=bool(answer and results),
        )
        return GraphAnswer(sub_answer=sub_answer, results=results)
