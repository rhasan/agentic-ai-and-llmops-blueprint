FROM python:3.12-slim

COPY --from=docker.io/astral/uv:latest /uv /uvx /bin/

# Trust the corp TLS-inspecting proxy CA (Zscaler) for outbound HTTPS to cloud
# model providers. Machine/network-specific; certs/ is gitignored — populate it
# with infra/serving/setup-cert.ps1. Empty dir (.gitkeep only) => no-op.
COPY infra/serving/certs/ /usr/local/share/ca-certificates/corp/
RUN update-ca-certificates

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project

COPY . .

RUN uv sync --frozen

# litellm reaches Azure via the openai SDK -> httpx, which trusts certifi's
# bundle, not the system store. Point Python TLS at the system bundle (now
# carrying the corp CA) AND fold the corp CA into certifi so both paths trust it.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
RUN cat /usr/local/share/ca-certificates/corp/*.crt \
    >> "$(uv run python -c 'import certifi; print(certifi.where())')" 2>/dev/null || true

EXPOSE 8000

# Online-path entry point: thin FastAPI over the orchestrator (/interpret,
# /answer). Connects out to the retrieval MCP server via SEARCH_MCP_URL.
CMD ["uv", "run", "uvicorn", "financial_doc_ai.serving.api:app", "--host", "0.0.0.0", "--port", "8000"]
