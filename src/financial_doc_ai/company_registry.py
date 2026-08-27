"""EDGAR company registry — cik <-> ticker <-> name.

Reference data derived from SEC's company_tickers.json (every filer). It is
external, re-fetchable lookup data, not our own audit evidence, so it lives at a
stable path (data/reference/company_tickers.json) and is refreshed in place
(latest-wins) rather than content-addressed like RawStore.

Two consumers: ingestion (resolve configured tickers -> CIK for fetching, and
stamp the canonical company id on filings) and the company resolver (build its
lookup table). Kept dumb: reads/writes the file, does no fetching itself — the
bytes come from the EdgarClient.
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path


class CompanyRegistry:
    URL_HINT = "https://www.sec.gov/files/company_tickers.json"

    def __init__(self, path: Path) -> None:
        # Source shape: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": ...}, ...}
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._by_ticker: dict[str, dict] = {}
        self._by_cik: dict[int, dict] = {}
        for row in data.values():
            self._by_ticker[row["ticker"].upper()] = row
            self._by_cik[int(row["cik_str"])] = row

    def cik_for(self, ticker: str) -> int | None:
        row = self._by_ticker.get(ticker.upper())
        return int(row["cik_str"]) if row else None

    def ticker_for(self, cik: int) -> str | None:
        row = self._by_cik.get(int(cik))
        return row["ticker"] if row else None

    def name_for(self, cik: int) -> str | None:
        row = self._by_cik.get(int(cik))
        return row["title"] if row else None

    @staticmethod
    def refresh(client, path: Path, log: Callable[[str], None] | None = None) -> None:
        """Fetch company_tickers.json and write it to `path`, skipping the write
        when the bytes are unchanged.

        Hashing happens after the fetch, so an unchanged file is still
        re-downloaded — the check saves the disk write and, more usefully, turns
        a real registry change (new filer, moved ticker/CIK) into a logged signal.
        """
        log = log or (lambda _msg: None)
        path = Path(path)
        data = client.fetch_company_tickers()
        new_hash = hashlib.sha256(data).hexdigest()
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == new_hash:
            log("company registry unchanged")
            return
        existed = path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        log("company registry updated" if existed else "company registry created")
