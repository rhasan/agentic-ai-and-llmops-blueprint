import hashlib
import json
from pathlib import Path


from financial_doc_ai.manifest import ManifestRecord

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
