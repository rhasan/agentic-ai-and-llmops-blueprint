import hashlib
import json
from pathlib import Path

from financial_doc_ai.storage.manifest import ManifestRecord


class RawStore:
    def __init__(self, root:Path):
        self.root = Path(root)
        self.manifest_path = self.root / "manifest.jsonl"

    def content_hash(self, data:bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def has_hash(self, content_hash: str) -> bool:
        if not self.manifest_path.exists():
            return False
        with self.manifest_path.open() as f:
            return any(json.loads(line)["content_hash"] == content_hash for line in f)

    def put(self, data: bytes, source: str, natural_id:str,
            fetched_at: str, source_metadata: dict) -> ManifestRecord | None:
        h = self.content_hash(data)
        if self.has_hash(h):
            return None  # idempotency: already stored

        path = self.root / "raw" / source / h
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

        record = ManifestRecord(
            natural_id=natural_id,
            content_hash=h,
            source=source,
            storage_path=str(path.relative_to(self.root)),
            fetched_at=fetched_at,
            source_metadata=source_metadata,
        )

        with self.manifest_path.open("a") as f:
            f.write(record.to_json() + "\n")
        return record


class ParsedStore:
    def __init__(self, root:Path):
        self.root = Path(root)
        # We use a separate manifest file for parsed files
        self.manifest_path = self.root / "parsed_manifest.jsonl"

    def content_hash(self, data:str) -> str:
        # We encode the text to bytes before hashing
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    def has_natural_id(self, natural_id: str) -> bool:
        """Check if we've already parsed the file with this ID."""
        if not self.manifest_path.exists():
            return False
        with self.manifest_path.open() as f:
            return any(json.loads(line)["natural_id"] == natural_id for line in f)

    def put(self, text: str, source: str, natural_id:str,
            fetched_at: str, source_metadata: dict) -> ManifestRecord | None:
        
        # Idempotency: Skip if we've already parsed this exact document
        if self.has_natural_id(natural_id):
            return None  

        h = self.content_hash(text)
        path = self.root / "parsed" / source / f"{h}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

        # Create a new manifest record pointing to the parsed markdown file
        record = ManifestRecord(
            natural_id=natural_id,
            content_hash=h,
            source=source,
            storage_path=str(path.relative_to(self.root)),
            fetched_at=fetched_at,
            source_metadata=source_metadata,
        )

        # Append the record to our parsed manifest
        with self.manifest_path.open("a") as f:
            f.write(record.to_json() + "\n")
            
        return record

class ChunkStore:
    """Stores the chunks of a document and records them in a manifest.

    All chunks of one document are written together as a single JSON file,
    and one line is appended to `chunk_manifest.jsonl` describing it.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        # Chunks get their own manifest, separate from raw and parsed.
        self.manifest_path = self.root / "chunk_manifest.jsonl"

    def has_natural_id(self, natural_id: str) -> bool:
        """Check if we've already chunked the document with this ID."""
        if not self.manifest_path.exists():
            return False
        with self.manifest_path.open() as f:
            return any(json.loads(line)["natural_id"] == natural_id for line in f)

    def put(
        self,
        chunks: list[dict],
        source: str,
        natural_id: str,
        fetched_at: str,
        source_metadata: dict,
        metadata: dict | None = None,
    ) -> ManifestRecord | None:
        # Idempotency: skip if this document has already been chunked.
        if self.has_natural_id(natural_id):
            return None

        # Write all chunks of this document into one JSON file. The chunks are
        # only meaningful together, so we don't split them across files. A
        # document-level `metadata` block (the retrieval filter fields, identical
        # for every chunk) makes the file self-describing; chunk-level attributes
        # (headers/is_table/chunk_index) stay on each chunk.
        payload = json.dumps(
            {"natural_id": natural_id, "metadata": metadata or {}, "chunks": chunks},
            ensure_ascii=False,
        )
        # Name the file by the hash of its contents, same as the other stores.
        h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        path = self.root / "chunks" / source / f"{h}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")

        # Record a manifest line pointing to that file. We also stash the
        # chunk count in the metadata so it's easy to inspect without opening
        # the file.
        record = ManifestRecord(
            natural_id=natural_id,
            content_hash=h,
            source=source,
            storage_path=str(path.relative_to(self.root)),
            fetched_at=fetched_at,
            source_metadata={**source_metadata, "chunk_count": len(chunks)},
        )
        with self.manifest_path.open("a") as f:
            f.write(record.to_json() + "\n")
        return record
