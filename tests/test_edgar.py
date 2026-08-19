import vcr
from financial_doc_ai.edgar import EdgarClient

# VCR config: where cassettes live, and record once then replay
my_vcr = vcr.VCR(
    cassette_library_dir="tests/cassettes",
    record_mode="once",
    filter_headers=["User-Agent"],
)

APPLE_CIK = 320193

@my_vcr.use_cassette("recent_filings.yaml")
def test_recent_filings():
    client = EdgarClient(user_agent="test-agent test@example.com")
    filings = client.recent_filings(cik=APPLE_CIK, form="10-K", limit=3)
    
    assert len(filings) == 3
    
    for f in filings:
        assert f["form"] == "10-K"
        assert f["accession"]
        assert f["primary_doc"]

@my_vcr.use_cassette("fetch_document.yaml")
def test_fetch_document():
    client = EdgarClient(user_agent="test-agent test@example.com")
    filings = client.recent_filings(cik=APPLE_CIK, form="10-K", limit=3)

    f = filings[0]
    data = client.fetch_document(APPLE_CIK, f["accession"], f["primary_doc"])
    assert len(data) > 0
    assert b"<html" in data[:2000].lower()
