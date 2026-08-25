"""Register seed prompts into Phoenix (idempotent, manifest-driven).

Reads ``seed/prompts/manifest.toml`` and, for each entry, creates version 1 from
the seed file if the prompt is not already in Phoenix, then tags that version with
the entry's label. Re-running is a no-op. Phoenix is the source of truth after
this; the seed files are the bootstrap for a fresh Phoenix and the runtime
fallback. Generic — adding a prompt is a manifest entry plus a file, no code change.
"""

import logging
import os

from phoenix.client import Client
from phoenix.client.types import PromptVersion

from financial_doc_ai.prompts import SEED_DIR, load_manifest

logger = logging.getLogger(__name__)


def main() -> None:
    client = Client(base_url=os.environ["PHOENIX_ENDPOINT"])

    for key, entry in load_manifest().items():
        name, label, file = entry["name"], entry["label"], entry["file"]
        try:
            client.prompts.get(prompt_identifier=name)
            logger.info("[%s] prompt %r already registered; skipping.", key, name)
            continue
        except ValueError:
            pass  # get raises ValueError on 404 -> prompt absent, create it

        seed_text = (SEED_DIR / file).read_text(encoding="utf-8")
        version = client.prompts.create(
            name=name,
            version=PromptVersion(
                [{"role": "system", "content": seed_text}],
                model_name=os.environ["QUERY_REWRITE_MODEL"],
            ),
        )
        client.prompts.tags.create(prompt_version_id=version.id, name=label)
        logger.info(
            "[%s] registered prompt %r (version %s) tagged %r.",
            key, name, version.id, label,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
