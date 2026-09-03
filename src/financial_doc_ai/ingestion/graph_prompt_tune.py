"""Auto-tune GraphRAG's indexing prompts against our own chunks (setup, run once).

This is the plan's *setup phase* (see docs/specs/graphrag-financial-doc-ai.md,
"Setup phase (done once)"): instead of hand-writing the extraction prompt, we let
the model read a sample of the corpus and generate, adapted to financial filings:
  1. a role/persona ("expert analyst of financial filings"),
  2. an entity-type list (company, supplier, contract, risk factor, person,
     committee, … — whatever it discovers), and
  3. few-shot extraction examples.
A human then reviews the result (mainly the entity types) and the reviewed prompts
are fixed — checked into git under config/graphrag/prompts/ and referenced from
settings.yaml. This is *not* a Dagster asset; it runs once during setup, not on
every ingestion.

Two things that are easy to get wrong, so they're spelled out here:

* Entity types are BAKED INTO extract_graph.txt, not kept as config.
  In the tuning template, `{entity_types}` is filled at tune time while
  `{{input_text}}` is escaped and survives as the only runtime placeholder. So the
  discovered types live literally inside extract_graph.txt, and the settings.yaml
  `entity_types` field is bypassed once this tuned prompt is used. To change the
  ontology after review, edit extract_graph.txt — not a config list.

* The tuner reads its sample from the config's INPUT STORAGE, not the in-process
  DataFrame the indexer uses (graph_indexer.build_index(input_documents=df)). So we
  dump our chunks to a throwaway text dir and point the tuner at it. With
  chunking.size huge (settings.yaml), one file = one chunk = one doc, so the tuner
  samples exactly the chunks the index will extract from.
"""

import asyncio
import os
import tempfile
from pathlib import Path

import pandas as pd
from graphrag.api.prompt_tune import generate_indexing_prompts
from graphrag.config.load_config import load_config
from graphrag.prompt_tune.types import DocSelectionType

from financial_doc_ai.ingestion.graph_indexer import (
    DATA_ROOT,
    GRAPHRAG_ROOT,
    _configure_models,
    build_documents_df,
)
from financial_doc_ai.storage import ChunkStore

PROMPTS_DIR = Path(GRAPHRAG_ROOT) / "prompts"

# Returned in the order generate_indexing_prompts yields them: extraction,
# entity/description summarization, community report summarization.
_FILENAMES = ("extract_graph.txt", "summarize_descriptions.txt", "community_report.txt")


def _write_chunk_inputs(df: pd.DataFrame, dest: Path) -> None:
    """Dump each chunk's text to its own .txt so GraphRAG's text reader can sample it."""
    dest.mkdir(parents=True, exist_ok=True)
    for row in df.itertuples(index=False):
        # "natural_id:idx" -> filesystem-safe filename; content is the chunk text.
        (dest / f"{row.id.replace(':', '_')}.txt").write_text(row.text, encoding="utf-8")


def tune_prompts(
    limit: int = 15,
    selection: DocSelectionType = DocSelectionType.RANDOM,
) -> Path:
    """Generate the three indexing prompts from a sample of our chunks and save them.

    `limit` = how many chunks the model reads to write the prompts (a sample, not
    the whole corpus). We tune over the full chunk store (not the GRAPHRAG_MAX_CHUNKS
    dev cap) so the prompts are representative. Returns the prompts directory.
    """
    df = build_documents_df(ChunkStore(DATA_ROOT))
    config = load_config(root_dir=Path(GRAPHRAG_ROOT))
    _configure_models(config)

    with tempfile.TemporaryDirectory() as tmp:
        _write_chunk_inputs(df, Path(tmp))
        config.input_storage.base_dir = tmp
        config.input.type = "text"
        prompts = asyncio.run(
            generate_indexing_prompts(
                config,
                limit=limit,
                selection_method=selection,
                discover_entity_types=True,  # generate the entity-type list from the corpus
            )
        )

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in zip(_FILENAMES, prompts, strict=True):
        (PROMPTS_DIR / name).write_text(text, encoding="utf-8")
    return PROMPTS_DIR


if __name__ == "__main__":
    out = tune_prompts()
    print(f"Wrote tuned prompts to {out}")
    print(f"REVIEW the entity types in {out / 'extract_graph.txt'} before indexing.")
