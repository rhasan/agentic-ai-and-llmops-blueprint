"""Prompt-registry access: manifest paths, manifest loading, and live-prompt fetch.

The single place that knows where the seed prompts live and how to read a prompt
from Phoenix. ``prompts.seed`` writes to the registry; components (e.g.
``query.rewriter``) read from it via ``fetch_system_prompt``.
"""

import logging
import os
import tomllib
from pathlib import Path

from phoenix.client import Client

logger = logging.getLogger(__name__)

# repo-root/seed/prompts/ — resolved from this file, not the working directory.
SEED_DIR = Path(__file__).resolve().parents[3] / "seed" / "prompts"
MANIFEST = SEED_DIR / "manifest.toml"


def load_manifest() -> dict:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))


def fetch_system_prompt(key: str) -> str:
    """Live system-prompt text for a manifest entry.

    Fetches the version currently tagged with the entry's label from Phoenix
    (the label is a movable pointer — promoting a new version in the UI changes
    what this returns). Falls back to the seed file if Phoenix is unreachable, so
    prompt fetch never breaks the query path.
    """
    spec = load_manifest()[key]
    try:
        client = Client(base_url=os.environ["PHOENIX_ENDPOINT"])
        version = client.prompts.get(prompt_identifier=spec["name"], tag=spec["label"])
        messages = version.format().messages
        return next(m["content"] for m in messages if m["role"] == "system")
    except Exception as e:
        logger.warning("Phoenix prompt fetch failed (%s); using seed file.", e)
        return (SEED_DIR / spec["file"]).read_text(encoding="utf-8")
