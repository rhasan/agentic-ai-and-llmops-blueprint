FROM python:3.12-slim

COPY --from=docker.io/astral/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project

COPY . .

RUN uv sync --frozen

EXPOSE 8000

# The online API entrypoint is a later step. Until it exists, run components via
# `docker compose run --rm app <cmd>` (overrides this CMD).
CMD ["uv", "run", "uvicorn", "financial_doc_ai.api:app", "--host", "0.0.0.0", "--port", "8000"]
