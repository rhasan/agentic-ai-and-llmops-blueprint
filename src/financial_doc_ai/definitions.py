import os
import json
from datetime import datetime, timezone
from pathlib import Path

import dagster as dg

from financial_doc_ai.edgar import EdgarClient
from financial_doc_ai.storage import RawStore, ParsedStore
from financial_doc_ai.parser import FilingParser


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

defs = dg.Definitions(assets=[raw_filings, parsed_filings])
