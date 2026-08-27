from pathlib import Path

import vcr

from financial_doc_ai.company_registry import CompanyRegistry
from financial_doc_ai.ingestion.edgar import EdgarClient

# Records the real SEC company_tickers.json once, then replays offline.
my_vcr = vcr.VCR(
    cassette_library_dir="tests/cassettes",
    record_mode="once",
    filter_headers=["User-Agent"],
)


def _client() -> EdgarClient:
    return EdgarClient(user_agent="test-agent test@example.com")


@my_vcr.use_cassette("company_tickers.yaml")
def test_refresh_creates_file_and_parses_real_data(tmp_path: Path):
    path = tmp_path / "company_tickers.json"
    logs: list[str] = []

    CompanyRegistry.refresh(_client(), path, log=logs.append)
    assert path.exists()
    assert any("created" in m for m in logs)

    reg = CompanyRegistry(path)
    # Parsed against the real SEC file shape (cik_str/ticker/title).
    assert reg.cik_for("AAPL") == 320193
    assert reg.cik_for("aapl") == 320193  # case-insensitive
    assert reg.ticker_for(320193) == "AAPL"
    assert "Apple" in reg.name_for(320193)
    # Unknown lookups return None (edge case, still against real data).
    assert reg.cik_for("NOT-A-REAL-TICKER") is None
    assert reg.ticker_for(-1) is None
    assert reg.name_for(-1) is None


# allow_playback_repeats: this test calls the endpoint twice under one cassette.
@my_vcr.use_cassette("company_tickers.yaml", allow_playback_repeats=True)
def test_refresh_skips_write_when_unchanged(tmp_path: Path):
    path = tmp_path / "company_tickers.json"
    logs: list[str] = []

    CompanyRegistry.refresh(_client(), path, log=logs.append)  # create
    CompanyRegistry.refresh(_client(), path, log=logs.append)  # same bytes replayed -> skip
    assert any("unchanged" in m for m in logs)


@my_vcr.use_cassette("company_tickers.yaml")
def test_refresh_updates_when_disk_differs(tmp_path: Path):
    path = tmp_path / "company_tickers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Pre-seed a stale cached file (test setup on disk, not a mocked call) so the
    # freshly fetched real bytes differ and trigger the update path.
    path.write_text('{"0": {"cik_str": 1, "ticker": "OLD", "title": "Old Co"}}', encoding="utf-8")
    logs: list[str] = []

    CompanyRegistry.refresh(_client(), path, log=logs.append)
    assert any("updated" in m for m in logs)
    assert CompanyRegistry(path).cik_for("AAPL") == 320193
