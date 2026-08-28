FROM python:3.12-slim

COPY --from=docker.io/astral/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project

COPY . .

RUN uv sync --frozen

EXPOSE 8001

# Retrieval exposed as an MCP server (streamable-http), reachable by any host on
# llm-net. See docs/retrieval-and-serving.md.
CMD ["uv", "run", "python", "-m", "financial_doc_ai.retrieval.server"]
