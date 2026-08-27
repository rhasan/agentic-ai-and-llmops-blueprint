"""Prompt registry: manifest access + live-prompt fetch (``registry``) and Phoenix
seeding (``seed``). Public helpers re-exported for stable import paths.
"""

from financial_doc_ai.prompts.registry import (
    MANIFEST,
    SEED_DIR,
    fetch_system_prompt,
    load_manifest,
)

__all__ = ["MANIFEST", "SEED_DIR", "fetch_system_prompt", "load_manifest"]
