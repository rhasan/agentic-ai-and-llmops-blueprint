import time
import httpx

class EdgarClient:
    """Downloads filings from SEC EDGAR.

    A "dumb" client: it only fetches data (filing lists and document bytes)
    and does no storage. It sends the required User-Agent header and rate-limits
    itself to stay under SEC's ~10 requests/second.
    """

    SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
    DOC = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

    def __init__(self, user_agent: str, min_interval: float = 0.15):
        self._client = httpx.Client(headers={"User-Agent": user_agent}, timeout=30.0)
        self._min_interval = min_interval  # ~6-7 req/s, safely under SEC's ~10
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()


    def recent_filings(self, cik: int, form: str, limit: int = 5) -> list[dict]:
        """Get the list of a company's recent filings of one form type.

        Asks EDGAR for the company's filing list, keeps only the given form
        (e.g. "10-K"), and returns up to `limit` of the most recent ones.
        Returns small dicts (accession, form, filing_date, primary_doc) — the
        list only, not the file contents.
        """
        self._throttle()
        r = self._client.get(self.SUBMISSIONS.format(cik=cik))
        r.raise_for_status()
        recent = r.json()["filings"]["recent"]
        out = []

        for i, f in enumerate(recent["form"]):
            if f == form:
                out.append(
                    {
                        "accession": recent["accessionNumber"][i],
                        "form": f,
                        "filing_date": recent["filingDate"][i],
                        "primary_doc": recent["primaryDocument"][i],
                    }
                )
            if len(out) >= limit:
                break
        return out

    def fetch_document(self, cik: int, accession: str, primary_doc: str) -> bytes:
        """Download one filing's primary document.

        Takes one filing's IDs (from `recent_filings`), builds its document
        URL, downloads it, and returns the raw bytes.
        """
        self._throttle()
        acc = accession.replace("-","")
        r = self._client.get(self.DOC.format(cik=cik, acc=acc, doc=primary_doc))
        r.raise_for_status()
        return r.content
