"""FilingSearch: real ephemeral Chroma + VCR-recorded Ollama embeddings.

Both the corpus embeddings (seed) and the query embedding are real nomic-embed-text
calls, recorded once and replayed offline — no fabricated vectors (a hand-written
768-d fixture would be exactly the kind of fake the VCR convention forbids, and
Chroma enforces one dimension per collection so it couldn't be faked short anyway).
The vector store is a real in-memory Chroma seeded in-test — hermetic, no service.

match_on includes the body so each distinct embedding request (2 seed texts vs. the
1 query text) maps to its own recorded interaction regardless of order.
"""

from pathlib import Path

import vcr

from financial_doc_ai.ingestion.embedder import Embedder
from financial_doc_ai.query.rewriter import Filters
from financial_doc_ai.retrieval.search import FilingSearch, _build_where
from financial_doc_ai.storage import VectorStore

my_vcr = vcr.VCR(
    cassette_library_dir="tests/cassettes",
    record_mode="once",
    match_on=["method", "scheme", "host", "port", "path", "body"],
)

# Pinned to what the cassette was recorded against; on replay VCR intercepts
# before any network so these need not resolve locally.
MODEL = "ollama/nomic-embed-text"
API_BASE = "http://ollama:11434"

_CORPUS = [
    ("AAPL-10K-2024", "Apple faces supply chain and competition risk factors.",
     {"company": "AAPL", "doc_type": "10-K", "period": "2024", "version": "current"},
     {"h1": "Item 1A"}),
    ("MSFT-10K-2024", "Microsoft cloud revenue grew year over year.",
     {"company": "MSFT", "doc_type": "10-K", "period": "2024", "version": "current"},
     {}),
]


def _embedder() -> Embedder:
    return Embedder(model=MODEL, api_base=API_BASE)


def _seed(tmp_path: Path, embedder: Embedder) -> VectorStore:
    vs = VectorStore(tmp_path / "chroma")
    vectors = embedder.embed([text for _, text, _, _ in _CORPUS])
    for (natural_id, text, fields, headers), vector in zip(_CORPUS, vectors, strict=True):
        vs.add_chunks(
            natural_id,
            [{"text": text, "is_table": False, "headers": headers, "chunk_index": 0}],
            [vector],
            MODEL,
            filter_metadata=fields,
        )
    return vs


@my_vcr.use_cassette("search_filings.yaml")
def test_company_filter_restricts_results(tmp_path: Path):
    embedder = _embedder()
    fs = FilingSearch(embedder=embedder, vector_store=_seed(tmp_path, embedder))
    results = fs.search("What are the risk factors?", Filters(company=["AAPL"]), top_k=5)

    assert results, "expected at least one hit"
    assert all(r.citation.company == "AAPL" for r in results)
    # Citation carries the stamped provenance + folded-back headers.
    top = results[0]
    assert top.citation.natural_id == "AAPL-10K-2024"
    assert top.citation.doc_type == "10-K"
    assert top.citation.period == "2024"
    assert top.citation.headers == {"h1": "Item 1A"}


@my_vcr.use_cassette("search_filings.yaml", allow_playback_repeats=True)
def test_no_filter_returns_all_companies(tmp_path: Path):
    embedder = _embedder()
    fs = FilingSearch(embedder=embedder, vector_store=_seed(tmp_path, embedder))
    # Same query text as the other test so it reuses the one recorded interaction
    # (record_mode="once" won't record a new request against an existing cassette).
    results = fs.search("What are the risk factors?", Filters(version=""), top_k=5)

    companies = {r.citation.company for r in results}
    assert companies == {"AAPL", "MSFT"}


def test_build_where_single_field():
    assert _build_where(Filters(company=["AAPL"], version="")) == {
        "company": {"$in": ["AAPL"]}
    }


def test_build_where_multi_company_uses_in():
    where = _build_where(Filters(company=["AAPL", "MSFT"], version=""))
    assert where == {"company": {"$in": ["AAPL", "MSFT"]}}


def test_build_where_multiple_fields_are_anded():
    where = _build_where(
        Filters(company=["AAPL"], doc_type=["10-K"], period=["2024"], version="current")
    )
    assert where == {
        "$and": [
            {"company": {"$in": ["AAPL"]}},
            {"doc_type": {"$in": ["10-K"]}},
            {"period": {"$in": ["2024"]}},
            {"version": "current"},
        ]
    }


def test_build_where_empty_is_none():
    # No fields set (version explicitly cleared) => no filter, not an empty dict
    # (Chroma rejects {}).
    assert _build_where(Filters(version="")) is None
