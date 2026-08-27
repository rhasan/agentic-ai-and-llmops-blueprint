"""Derive retrieval filter fields from a filing's source metadata.

Pure function: it reads fields already stamped on the manifest at fetch time
(ticker/form/report_date) and maps them to the four filter fields retrieval
uses — company / doc_type / period / version. Dependency-free so it is trivially
testable, and stamped onto every chunk's vector metadata at embed time.
"""


def chunk_filter_fields(source_metadata: dict) -> dict:
    fields: dict = {
        "doc_type": source_metadata["form"],
        # report_date is the fiscal-period end (e.g. "2024-09-28"); the fiscal
        # year is its leading 4 digits. (filing_date would be wrong — Apple's
        # FY2024 10-K is filed in late 2024 but the period ends in September.)
        "period": source_metadata["report_date"][:4],
        # Supersession (a re-filed same-period doc, e.g. a 10-K/A) is not in the
        # corpus yet, so every chunk is the current version. TODO: mark older
        # filings of the same (company, doc_type, period) as "superseded".
        "version": "current",
    }
    # Canonical company id is the ticker resolved from the registry at fetch
    # time. If it is missing (unknown filer), omit the field rather than guess.
    ticker = source_metadata.get("ticker")
    if ticker:
        fields["company"] = ticker
    return fields
