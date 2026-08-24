import os
import json
from datetime import datetime, timezone
from pathlib import Path

import dagster as dg

from financial_doc_ai.edgar import EdgarClient
from financial_doc_ai.storage import RawStore, ParsedStore, ChunkStore
from financial_doc_ai.parser import FilingParser
from financial_doc_ai.chunker import MarkdownChunker
from financial_doc_ai.embedder import Embedder
from financial_doc_ai.vector_store import VectorStore



@dg.asset
def raw_filings(context: dg.AssetExecutionContext) -> None:
    """Download recent filings and store them.

    Ties the client and store together: gets the list of recent filings
    (currently 3 Apple 10-Ks), downloads each one, and hands the bytes to
    RawStore to save and record. Duplicates are skipped by content hash.
    """
    client = EdgarClient(user_agent=os.environ["EDGAR_USER_AGENT"])
    store = RawStore(Path("/app/data"))

    cik, form = 320193, "10-K"  # Apple, hardcoded for first slice
    filings = client.recent_filings(cik=cik, form=form, limit=3)
    context.log.info(f"found {len(filings)} {form} filings for CIK {cik}")

    for f in filings:
        data = client.fetch_document(cik, f["accession"], f["primary_doc"])

        rec = store.put(
            data=data,
            source="edgar",
            natural_id=f["accession"],
            fetched_at=datetime.now(timezone.utc).isoformat(),
            source_metadata={
                "cik": cik, "form": form, "filing_date": f["filing_date"],
                "primary_doc": f["primary_doc"]
            },
        )
        context.log.info(f"{'stored' if rec else 'skipped (dup)'}: {f['accession']}")


@dg.asset(deps=[raw_filings])
def parsed_filings(context: dg.AssetExecutionContext) -> None:
    """Parses raw HTML filings into clean Markdown."""
    raw_store = RawStore(Path("/app/data"))
    parsed_store = ParsedStore(Path("/app/data"))
    parser = FilingParser()

    if not raw_store.manifest_path.exists():
        context.log.info("No raw filings to parse.")
        return

    # Loop through the raw manifest to find files we've downloaded
    with raw_store.manifest_path.open() as f:
        for line in f:
            rec = json.loads(line)
            
            # Idempotency check: Have we already parsed this one?
            if parsed_store.has_natural_id(rec["natural_id"]):
                context.log.info(f"Skipping already parsed: {rec['natural_id']}")
                continue
            
            raw_path = raw_store.root / rec["storage_path"]
            if not raw_path.exists():
                context.log.warning(f"Raw file missing for {rec['natural_id']}")
                continue

            context.log.info(f"Parsing: {rec['natural_id']}")
            
            # Read raw bytes, parse them, and store the markdown
            html_bytes = raw_path.read_bytes()
            md_text = parser.parse_html(html_bytes)
            
            parsed_store.put(
                text=md_text,
                source=rec["source"],
                natural_id=rec["natural_id"],
                fetched_at=datetime.now(timezone.utc).isoformat(),
                source_metadata=rec.get("source_metadata", {})
            )
            context.log.info(f"Successfully parsed and stored: {rec['natural_id']}")


@dg.asset(deps=[parsed_filings])
def chunked_filings(context: dg.AssetExecutionContext) -> None:
  """Chunks parsed Markdown into retrieval units, keeping tables whole."""
  parsed_store = ParsedStore(Path("/app/data"))
  chunk_store = ChunkStore(Path("/app/data"))
  chunker = MarkdownChunker()

  # Nothing to do if the parse stage hasn't produced anything yet.
  if not parsed_store.manifest_path.exists():
      context.log.info("No parsed filings to chunk.")
      return

  # Go through every parsed document listed in the parsed manifest.
  with parsed_store.manifest_path.open() as f:
      for line in f:
          rec = json.loads(line)
          # Skip documents we've already chunked (idempotent re-runs).
          if chunk_store.has_natural_id(rec["natural_id"]):
              context.log.info(f"Skipping already chunked: {rec['natural_id']}")
              continue
          # The parsed Markdown file the manifest line points to.
          parsed_path = parsed_store.root / rec["storage_path"]
          if not parsed_path.exists():
              context.log.warning(f"Parsed file missing for {rec['natural_id']}")
              continue

          # Read the Markdown, split it into chunks, and store them.
          md = parsed_path.read_text(encoding="utf-8")
          chunks = chunker.chunk(md)
          chunk_store.put(
              chunks=chunks, source=rec["source"],
              natural_id=rec["natural_id"],
              fetched_at=datetime.now(timezone.utc).isoformat(),
              source_metadata=rec.get("source_metadata", {}),
          )
          context.log.info(f"Chunked {rec['natural_id']}: {len(chunks)} chunks")


@dg.asset(deps=[chunked_filings])
def embedded_chunks(context: dg.AssetExecutionContext) -> None:
    """Embeds chunks and stores them in the vector store, idempotent per document."""
    chunk_store = ChunkStore(Path("/app/data"))
    vector_store = VectorStore(Path("/app/data/chroma"))
    embedder = Embedder()

    # Nothing to do if the chunk stage hasn't produced anything yet.
    if not chunk_store.manifest_path.exists():
        context.log.info("No chunked filings to embed.")
        return

    # Walk the chunk manifest, one line per chunked document.
    with chunk_store.manifest_path.open() as f:
        for line in f:
            rec = json.loads(line)
            # Skip documents already embedded (idempotent re-runs).
            if vector_store.has_natural_id(rec["natural_id"]):
                context.log.info(f"Skipping already embedded: {rec['natural_id']}")
                continue

            # The chunks file this manifest line points to.
            chunk_path = chunk_store.root / rec["storage_path"]
            if not chunk_path.exists():
                context.log.warning(f"Chunk file missing for {rec['natural_id']}")
                continue

            # Load the chunks, embed their text, store vectors + metadata.
            chunks = json.loads(chunk_path.read_text(encoding="utf-8"))["chunks"]
            embeddings = embedder.embed([c["text"] for c in chunks])
            vector_store.add_chunks(
                natural_id=rec["natural_id"],
                chunks=chunks,
                embeddings=embeddings,
                embedding_model=embedder.model,
            )
            context.log.info(f"Embedded {rec['natural_id']}: {len(chunks)} chunks")


defs = dg.Definitions(assets=[raw_filings, parsed_filings, chunked_filings, embedded_chunks])
