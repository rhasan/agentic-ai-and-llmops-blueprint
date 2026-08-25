from financial_doc_ai.company_resolver import CompanyResolver


def test_resolve_known_forms():
    r = CompanyResolver()
    for form in ("Apple", "aapl", "Apple Inc."):
        (res,) = r.resolve([form])
        assert res.outcome == "resolved"
        assert res.match_type == "exact"
        assert res.canonical is not None
        assert res.canonical.ticker == "AAPL"


def test_resolve_is_case_and_whitespace_insensitive():
    (res,) = CompanyResolver().resolve(["  APPLE "])
    assert res.outcome == "resolved"
    assert res.canonical.ticker == "AAPL"


def test_resolve_unknown_is_not_found():
    (res,) = CompanyResolver().resolve(["Microsoft"])
    assert res.outcome == "not_found"
    assert res.canonical is None


def test_resolve_preserves_order_and_input():
    results = CompanyResolver().resolve(["Microsoft", "Apple"])
    assert [r.input for r in results] == ["Microsoft", "Apple"]
    assert [r.outcome for r in results] == ["not_found", "resolved"]
