"""The one behaviour worth pinning: no Phoenix endpoint, no tracing setup.

Everything in the suite runs with no ``PHOENIX_ENDPOINT``, so ``setup_tracing``
has to be a silent no-op there — otherwise importing the API starts an exporter
that retries against a host that isn't up. The rest of step 1 is wiring, verified
by looking at a trace in the Phoenix UI, not by asserting here.
"""

import logging

from financial_doc_ai.telemetry import setup_tracing


def test_no_endpoint_is_a_noop(monkeypatch, caplog):
    monkeypatch.delenv("PHOENIX_ENDPOINT", raising=False)

    with caplog.at_level(logging.INFO, logger="financial_doc_ai.telemetry"):
        setup_tracing("test")

    assert "tracing disabled" in caplog.text
