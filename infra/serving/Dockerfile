FROM python:3.12-slim

COPY --from=docker.io/astral/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project

COPY . .

RUN uv sync --frozen

EXPOSE 8000

# Online-path entry point: thin FastAPI over the orchestrator (/interpret,
# /answer). Connects out to the retrieval MCP server via SEARCH_MCP_URL.
CMD ["uv", "run", "uvicorn", "financial_doc_ai.serving.api:app", "--host", "0.0.0.0", "--port", "8000"]
