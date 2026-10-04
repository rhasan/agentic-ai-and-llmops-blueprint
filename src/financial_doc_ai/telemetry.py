"""OpenTelemetry setup: send this process's spans to Phoenix.

Called once at process start. It creates the tracer provider the process is
missing — without one, anything emitting spans is talking to a no-op — and
switches on PydanticAI's own instrumentation, which describes agent runs, model
calls and tool calls as spans. We author no spans here.

Traces do not cross the MCP transport, so each process traces independently and
the traces meet only in Phoenix. ``project_name`` is the Phoenix bucket they land
in, passed at the call site rather than read from the environment: it says *which
process this is*, and every container shares one ``.env``.
"""

import logging
import os

from phoenix.otel import register
from pydantic_ai import Agent, InstrumentationSettings

logger = logging.getLogger(__name__)


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
        # batch=True keeps export off the request path: the default processor
        # ships each span inline as it ends.
        provider = register(endpoint=collector, project_name=project_name, batch=True)
        Agent.instrument_all(InstrumentationSettings(tracer_provider=provider))
        logger.info("Tracing to Phoenix at %s (project %r).", collector, project_name)
    except Exception as e:
        # Observability is not on the critical path — same rule as the prompt
        # registry's fallback. An unreachable Phoenix must not stop answering.
        logger.warning("Tracing setup failed (%s); continuing untraced.", e)
