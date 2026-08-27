from financial_doc_ai.ingestion.metadata import chunk_filter_fields


def test_maps_all_filter_fields():
    src = {
        "cik": 320193,
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "form": "10-K",
        "filing_date": "2024-11-01",  # deliberately different year from period end
        "report_date": "2024-09-28",
    }
    assert chunk_filter_fields(src) == {
        "company": "AAPL",
        "doc_type": "10-K",
        "period": "2024",  # from report_date, not filing_date
        "version": "current",
    }


def test_missing_ticker_omits_company():
    src = {"form": "10-K", "report_date": "2023-09-30"}
    fields = chunk_filter_fields(src)
    assert "company" not in fields
    assert fields["doc_type"] == "10-K"
    assert fields["period"] == "2023"
