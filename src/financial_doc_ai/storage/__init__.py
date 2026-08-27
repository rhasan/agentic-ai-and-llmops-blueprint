"""Persistence layer: raw/parsed/chunk stores, manifest record, and the vector store.

Re-exported here so call sites import from ``financial_doc_ai.storage`` regardless
of which submodule a class lives in.
"""

from financial_doc_ai.storage.manifest import ManifestRecord
from financial_doc_ai.storage.stores import ChunkStore, ParsedStore, RawStore
from financial_doc_ai.storage.vector_store import VectorStore

__all__ = [
    "ChunkStore",
    "ManifestRecord",
    "ParsedStore",
    "RawStore",
    "VectorStore",
]
