"""Retrieval core: filter-aware similarity search over the stamped vector index.

Plain library code, deliberately independent of the MCP transport (server.py is a
thin adapter over this). The tool is dumb: confirmed, canonical filters in, chunks
out. Query rewrite / company resolution / the confirmation gate all happen upstream
in the orchestrator — not here. See docs/retrieval-and-serving.md.
"""

from pydantic import BaseModel

from financial_doc_ai.ingestion.embedder import Embedder
from financial_doc_ai.query.rewriter import Filters
from financial_doc_ai.storage import VectorStore


class Citation(BaseModel):
    """What makes a returned passage citable — the stamped provenance fields."""

    natural_id: str
    company: str | None = None
    doc_type: str | None = None
    period: str | None = None
    version: str | None = None
    chunk_index: int | None = None
    headers: dict[str, str] = {}


class SearchResult(BaseModel):
    text: str
    distance: float
    citation: Citation


# Chroma reserves these metadata keys for chunk-level attributes; everything else
# stamped on a vector is a header level (h1/h2/...) we fold back into the citation.
_RESERVED_META = {
    "natural_id",
    "company",
    "doc_type",
    "period",
    "version",
    "chunk_index",
    "is_table",
    "embedding_model",
}


def _build_where(filters: Filters) -> dict | None:
    """Translate the four filter fields into a Chroma `where` clause.

    List fields become `$in`; the scalar `version` an equality. Multiple
    conditions are `$and`-ed. Returns None when nothing is set (Chroma rejects an
    empty filter). The corpus is stamped with canonical values (company=ticker,
    doc_type="10-K", period="2024", version="current"), so callers must pass
    already-resolved filters for a match.
    """
    clauses: list[dict] = []
    if filters.company:
        clauses.append({"company": {"$in": filters.company}})
    if filters.doc_type:
        clauses.append({"doc_type": {"$in": filters.doc_type}})
    if filters.period:
        clauses.append({"period": {"$in": filters.period}})
    if filters.version:
        clauses.append({"version": filters.version})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


class FilingSearch:
    def __init__(
        self,
        embedder: Embedder | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        # Injectable so tests pass a real ephemeral store + a VCR-backed embedder,
        # mirroring QueryPipeline's construction style.
        self.embedder = embedder if embedder is not None else Embedder()
        self.vector_store = vector_store if vector_store is not None else VectorStore()

    def search(
        self, query: str, filters: Filters, top_k: int = 5
    ) -> list[SearchResult]:
        # Embed the query with the SAME model the corpus was embedded with — a
        # mismatched model puts the query in a different space and breaks recall.
        embedding = self.embedder.embed([query])[0]
        where = _build_where(filters)
        raw = self.vector_store.query(embedding, where=where, n_results=top_k)
        return self._shape(raw)

    @staticmethod
    def _shape(raw: dict) -> list[SearchResult]:
        # Chroma returns parallel arrays nested one level per query; we issue one
        # query, so index [0]. Empty corpus / no match => empty lists.
        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]

        results: list[SearchResult] = []
        for text, meta, distance in zip(documents, metadatas, distances, strict=True):
            headers = {k: v for k, v in meta.items() if k not in _RESERVED_META}
            results.append(
                SearchResult(
                    text=text,
                    distance=distance,
                    citation=Citation(
                        natural_id=meta.get("natural_id", ""),
                        company=meta.get("company"),
                        doc_type=meta.get("doc_type"),
                        period=meta.get("period"),
                        version=meta.get("version"),
                        chunk_index=meta.get("chunk_index"),
                        headers=headers,
                    ),
                )
            )
        return results
