"""Chroma wrapper — persists chunk embeddings + metadata for retrieval."""

import os
from pathlib import Path

import chromadb
from chromadb.config import Settings


class VectorStore:
    def __init__(
        self, path: Path | None = None, collection_name: str = "chunks"
    ) -> None:
        # Default the on-disk location from env (CHROMA_PATH) so the retrieval
        # server can construct one with no args, like Embedder reads its config
        # from env. Callers that know the path (Dagster assets, tests) still pass
        # it explicitly.
        path = path if path is not None else Path(os.environ.get("CHROMA_PATH", "data/chroma"))
        # PersistentClient writes to disk (data/chroma/), so vectors survive
        # container restarts. Telemetry off — no phone-home from a blueprint.
        client = chromadb.PersistentClient(
            path=str(path),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = client.get_or_create_collection(name=collection_name)

    def has_natural_id(self, natural_id: str) -> bool:
        # Ask for one row tagged with this document id; empty result => not stored.
        result = self.collection.get(where={"natural_id": natural_id}, limit=1)
        return len(result["ids"]) > 0

    def add_chunks(
        self,
        natural_id: str,
        chunks: list[dict],
        embeddings: list[list[float]],
        embedding_model: str,
        filter_metadata: dict | None = None,
    ) -> None:
        # Retrieval filter fields (company/doc_type/period/version), same for
        # every chunk of a document. All scalars, so Chroma-safe.
        filter_metadata = filter_metadata or {}
        ids, metadatas = [], []
        for chunk in chunks:
            # Deterministic id: same doc+position => same id, so a re-add would
            # overwrite rather than duplicate. natural_id ties chunks back to
            # their source document.
            ids.append(f"{natural_id}:{chunk['chunk_index']}")

            meta = {
                "natural_id": natural_id,
                "chunk_index": chunk["chunk_index"],
                "is_table": chunk["is_table"],
                "embedding_model": embedding_model,
                **filter_metadata,
            }
            # Chroma metadata values must be scalars (no dicts/None). Flatten the
            # header map, keeping only the levels that are present.
            for level, text in chunk["headers"].items():
                meta[level] = text
            metadatas.append(meta)

        self.collection.add(
            ids=ids,
            documents=[c["text"] for c in chunks],
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query(
        self,
        embedding: list[float],
        where: dict | None = None,
        n_results: int = 5,
    ) -> dict:
        # Metadata-filtered similarity search. Chroma rejects an empty {} filter,
        # so pass None when there is nothing to filter on. Returns Chroma's raw
        # parallel-array result dict; the caller shapes it into domain objects.
        return self.collection.query(
            query_embeddings=[embedding],
            where=where or None,
            n_results=n_results,
        )
