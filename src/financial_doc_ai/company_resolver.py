"""Company resolver: surface form -> canonical id (ticker).

Deterministic, separate from the query-rewrite LLM: query rewrite extracts the
surface form the analyst wrote; this maps it to the canonical company. See
docs/query-rewrite-strategy.md ("Company resolver") for the contract.

DUMMY IMPLEMENTATION: exact dict lookup against a hardcoded registry. It exists so
the call site is in place; it does not yet do alias/fuzzy matching or ambiguity.
TODO: build the registry from the ingested-corpus metadata (EDGAR CIK/ticker/name)
and add fuzzy matching + ambiguous outcomes.
"""

from typing import Literal

from pydantic import BaseModel


class Canonical(BaseModel):
    ticker: str
    name: str
    cik: str


class Resolution(BaseModel):
    input: str
    outcome: Literal["resolved", "not_found", "ambiguous"]
    canonical: Canonical | None = None
    match_type: Literal["exact", "alias", "fuzzy"] | None = None
    candidates: list[Canonical] | None = None


_APPLE = Canonical(ticker="AAPL", name="Apple Inc.", cik="320193")

# Registry: surface form (lowercased) -> canonical. One entry today (Apple); the
# mechanism is the point, not the scale. Later built from ingested metadata.
_REGISTRY: dict[str, Canonical] = {
    alias: _APPLE for alias in ("apple", "apple inc", "apple inc.", "aapl")
}


class CompanyResolver:
    def __init__(self, registry: dict[str, Canonical] | None = None) -> None:
        self._registry = registry if registry is not None else _REGISTRY

    def resolve(self, surface_forms: list[str]) -> list[Resolution]:
        """Resolve each surface form independently. Dummy: exact lookup only."""
        results: list[Resolution] = []
        for form in surface_forms:
            hit = self._registry.get(form.strip().lower())
            if hit is not None:
                results.append(
                    Resolution(input=form, outcome="resolved", canonical=hit, match_type="exact")
                )
            else:
                results.append(Resolution(input=form, outcome="not_found"))
        return results


if __name__ == "__main__":
    resolver = CompanyResolver()
    for res in resolver.resolve(["Apple", "Apple Inc", "Microsoft"]):
        print(res.model_dump(exclude_none=True))
