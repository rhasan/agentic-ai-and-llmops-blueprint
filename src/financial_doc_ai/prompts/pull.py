"""Copy the live prompts out of Phoenix back into the seed files.

The mirror of ``prompts.seed``: ``seed`` pushes the seed files into a fresh Phoenix,
this pulls Phoenix's current text back down.

Phoenix is the source of truth — prompts are edited in its UI. The seed files have
two jobs that both go stale when that happens: they bootstrap an empty Phoenix, and
they are the runtime fallback when Phoenix is unreachable
(``registry.fetch_system_prompt``). A stale fallback is the dangerous one: the app
keeps serving, quietly using an old prompt. Running this after a UI edit keeps the
files honest and puts the change in git history, where prompt edits are reviewable
like any other change.

Reads the version tagged with each manifest entry's label — the same read the app
does on every request — and writes it over the entry's file.

    uv run python -m financial_doc_ai.prompts.pull

Then `git diff seed/prompts/` shows what changed in the UI, and you commit it.
"""

import logging
import os

from phoenix.client import Client

from financial_doc_ai.prompts.registry import SEED_DIR, load_manifest

logger = logging.getLogger(__name__)


def main() -> None:
    client = Client(base_url=os.environ["PHOENIX_ENDPOINT"])
    changed = 0

    for key, entry in load_manifest().items():
        name, label, file = entry["name"], entry["label"], entry["file"]
        path = SEED_DIR / file

        try:
            version = client.prompts.get(prompt_identifier=name, tag=label)
        except ValueError:
            # Not in Phoenix (or nothing carries the label) — there is nothing to
            # pull. Leave the file alone: it is still the bootstrap source, and
            # `prompts.seed` is what pushes it up.
            logger.warning(
                "[%s] %r not found at label %r in Phoenix; leaving %s untouched.",
                key, name, label, file,
            )
            continue

        messages = version.format().messages
        live = next((m["content"] for m in messages if m["role"] == "system"), None)
        if live is None:
            logger.warning("[%s] %r has no system message; skipping.", key, name)
            continue

        # Compare stripped, write with a single trailing newline, so re-running
        # produces no spurious diff from whitespace alone.
        on_disk = path.read_text(encoding="utf-8") if path.exists() else ""
        if on_disk.strip() == live.strip():
            logger.info("[%s] %s already matches Phoenix.", key, file)
            continue

        path.write_text(live.strip() + "\n", encoding="utf-8")
        changed += 1
        logger.info("[%s] UPDATED %s from Phoenix.", key, file)

    if changed:
        logger.info(
            "%d prompt file(s) updated. Review with `git diff seed/prompts/` "
            "and commit.", changed
        )
    else:
        logger.info("All prompt files already match Phoenix; nothing to do.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
