"""OpenTelemetry setup: send this process's spans to Phoenix.

Called once at process start. It creates the tracer provider the process is
missing — without one, anything emitting spans is talking to a no-op — and
switches on the instrumentation that describes the work: PydanticAI's own for the
agent loop, OpenInference's for the LiteLLM calls underneath retrieval and
GraphRAG. We author no spans here.

The MCP SDK carries the caller's trace id across the transport, so the serving
process and both MCP servers land in one trace per question. That only renders as
one tree inside a single Phoenix project, so every online process passes the same
``project_name``. It is an argument rather than an environment variable because
it says *which workload this is*, and every container shares one ``.env``.
"""

import logging
import os
from collections.abc import Sequence

from openinference.instrumentation.litellm import LiteLLMInstrumentor
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from phoenix.otel import (
    PROJECT_NAME,
    BatchSpanProcessor,
    HTTPSpanExporter,
    Resource,
    TracerProvider,
)
from pydantic_ai import Agent, InstrumentationSettings

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL_NAME = "embedding.model_name"
_LLM_MODEL_NAME = "llm.model_name"


class _PriceableEmbeddings(SpanExporter):
    """Name an embedding span's model where Phoenix looks for it.

    Phoenix prices a span by matching its configured models against the
    ``llm.model_name`` attribute (``cost_tracking.cost_model_lookup``), but
    OpenInference records an embedding's model under ``embedding.model_name``.
    The mismatch is silent: the span shows its token count and a cost of zero, no
    matter what price is configured. The embedding tokens are a small share of a
    query's spend, but "small" is not something an unpriced span can tell you.

    Spans are immutable once ended, so this re-emits a copy with the attribute
    added. Everything else passes through untouched.
    """

    def __init__(self, wrapped: SpanExporter) -> None:
        self._wrapped = wrapped

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._wrapped.export([self._named_for_pricing(s) for s in spans])

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._wrapped.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self._wrapped.shutdown()

    @staticmethod
    def _named_for_pricing(span: ReadableSpan) -> ReadableSpan:
        attributes = span.attributes or {}
        if _LLM_MODEL_NAME in attributes or _EMBEDDING_MODEL_NAME not in attributes:
            return span
        return ReadableSpan(
            name=span.name,
            context=span.context,
            parent=span.parent,
            resource=span.resource,
            attributes={
                **attributes,
                _LLM_MODEL_NAME: attributes[_EMBEDDING_MODEL_NAME],
            },
            events=span.events,
            links=span.links,
            kind=span.kind,
            status=span.status,
            start_time=span.start_time,
            end_time=span.end_time,
            instrumentation_scope=span.instrumentation_scope,
        )


def setup_tracing(project_name: str) -> None:
    endpoint = os.environ.get("PHOENIX_ENDPOINT")
    if not endpoint:
        logger.info("PHOENIX_ENDPOINT unset; tracing disabled.")
        return

    # PHOENIX_ENDPOINT is the server's base URL (the prompt client wants that);
    # the OTLP collector is a path on it. Passing the base alone posts to `/` and
    # Phoenix answers 405.
    collector = f"{endpoint.rstrip('/')}/v1/traces"

    try:
        # Built from `phoenix.otel`'s drop-in pieces rather than its one-call
        # `register()`, which owns its exporter and leaves nowhere to wrap one.
        # BatchSpanProcessor keeps export off the request path.
        provider = TracerProvider(resource=Resource({PROJECT_NAME: project_name}))
        provider.add_span_processor(
            BatchSpanProcessor(
                span_exporter=_PriceableEmbeddings(HTTPSpanExporter(endpoint=collector))
            )
        )
        # Global, because the MCP SDK's own spans — the ones that carry the trace
        # across the transport — are written against whatever provider is global.
        trace.set_tracer_provider(provider)

        Agent.instrument_all(InstrumentationSettings(tracer_provider=provider))

        # The model calls that don't go through PydanticAI — the query embedding in
        # `search_filings`, GraphRAG's DRIFT calls in `graph_search` — all reach
        # their provider via LiteLLM. This instruments its entry points, so those
        # calls arrive as LLM/EMBEDDING spans carrying token counts. LiteLLM's own
        # `callbacks = ["otel"]` propagates and nests correctly too, but records
        # raw request dumps with no usable token attributes, which leaves the cost
        # signal uncomputable. A no-op where LiteLLM is unused.
        LiteLLMInstrumentor().instrument(tracer_provider=provider)

        logger.info("Tracing to Phoenix at %s (project %r).", collector, project_name)
    except Exception as e:
        # Observability is not on the critical path — same rule as the prompt
        # registry's fallback. An unreachable Phoenix must not stop answering.
        logger.warning("Tracing setup failed (%s); continuing untraced.", e)
