from dataclasses import dataclass, asdict, field
import json

@dataclass(frozen=True)
class ManifestRecord:
    natural_id: str
    content_hash: str
    source: str
    storage_path: str
    fetched_at: str
    source_metadata: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))
