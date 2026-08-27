import json
import os
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import dagster as dg

from financial_doc_ai.company_registry import CompanyRegistry
from financial_doc_ai.ingestion.chunker import MarkdownChunker
from financial_doc_ai.ingestion.edgar import EdgarClient
from financial_doc_ai.ingestion.embedder import Embedder
from financial_doc_ai.ingestion.metadata import chunk_filter_fields
from financial_doc_ai.ingestion.parser import FilingParser
from financial_doc_ai.storage import ChunkStore, ParsedStore, RawStore, VectorStore

CONFIG_PATH = Path("/app/config/companies.toml")
REGISTRY_PATH = Path("/app/data/reference/company_tickers.json")



@dg.asset
def raw_filings(context: dg.AssetExecutionContext) -> None:
    """Download recent filings and store them.

    Driven by config/companies.toml (which tickers/forms to pull). Refreshes the
    EDGAR company registry, resolves each configured ticker to its CIK + canonical
    name, downloads each filing, and hands the bytes to RawStore. The canonical
    ticker/name and fiscal period_date are stamped into source_metadata so the
    retrieval filter fields can be derived downstream. Duplicates skipped by hash.
    """
    client = EdgarClient(user_agent=os.environ["EDGAR_USER_AGENT"])
    store = RawStore(Path("/app/data"))

    config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    tickers, forms = config["tickers"], config["forms"]

    # Reference registry: fetch once (latest-wins), then look CIKs up locally.
    CompanyRegistry.refresh(client, REGISTRY_PATH, log=context.log.info)
    registry = CompanyRegistry(REGISTRY_PATH)

    for ticker in tickers:
        cik = registry.cik_for(ticker)
        if cik is None:
            context.log.warning(f"ticker {ticker} not in EDGAR registry; skipping")
            continue
        company_name = registry.name_for(cik)

        for form in forms:
            filings = client.recent_filings(cik=cik, form=form, limit=3)
            context.log.info(f"found {len(filings)} {form} filings for {ticker} (CIK {cik})")

            for f in filings:
                data = client.fetch_document(cik, f["accession"], f["primary_doc"])
                rec = store.put(
                    data=data,
                    source="edgar",
                    natural_id=f["accession"],
                    fetched_at=datetime.now(UTC).isoformat(),
                    source_metadata={
                        "cik": cik,
                        "ticker": ticker,
                        "company_name": company_name,
                        "form": form,
                        "filing_date": f["filing_date"],
                        "report_date": f["report_date"],
                        "primary_doc": f["primary_doc"],
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
                fetched_at=datetime.now(UTC).isoformat(),
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

          # Read the Markdown, split it into chunks, and store them. Derive the
          # document-level filter fields here (single derivation point) and stash
          # them in the chunk file so it is self-describing.
          md = parsed_path.read_text(encoding="utf-8")
          chunks = chunker.chunk(md)
          filter_metadata = chunk_filter_fields(rec["source_metadata"])
          chunk_store.put(
              chunks=chunks, source=rec["source"],
              natural_id=rec["natural_id"],
              fetched_at=datetime.now(UTC).isoformat(),
              source_metadata=rec.get("source_metadata", {}),
              metadata=filter_metadata,
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
            payload = json.loads(chunk_path.read_text(encoding="utf-8"))
            chunks = payload["chunks"]
            embeddings = embedder.embed([c["text"] for c in chunks])
            # The chunk file already carries the document-level filter fields
            # (company/doc_type/period/version); stamp them onto every vector so
            # retrieval can filter on real metadata.
            vector_store.add_chunks(
                natural_id=rec["natural_id"],
                chunks=chunks,
                embeddings=embeddings,
                embedding_model=embedder.model,
                filter_metadata=payload.get("metadata", {}),
            )
            context.log.info(f"Embedded {rec['natural_id']}: {len(chunks)} chunks")


defs = dg.Definitions(assets=[raw_filings, parsed_filings, chunked_filings, embedded_chunks])
