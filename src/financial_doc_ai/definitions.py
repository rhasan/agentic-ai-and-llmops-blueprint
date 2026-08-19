import os
from datetime import datetime, timezone
from pathlib import Path

import dagster as dg

from financial_doc_ai.edgar import EdgarClient
from financial_doc_ai.storage import RawStore


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

defs = dg.Definitions(assets=[raw_filings])
