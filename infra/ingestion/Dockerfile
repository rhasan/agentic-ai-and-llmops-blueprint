FROM python:3.12-slim

COPY --from=docker.io/astral/uv:latest /uv /uvx /bin/

# Trust the corp TLS-inspecting proxy CA (Zscaler) for outbound HTTPS to cloud
# model providers. Machine/network-specific; certs/ is gitignored — populate it
# with infra/ingestion/setup-cert.ps1. Empty dir (.gitkeep only) => no-op.
COPY infra/ingestion/certs/ /usr/local/share/ca-certificates/corp/
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

EXPOSE 3000

CMD ["uv", "run", "dagster", "dev", "-h", "0.0.0.0", "-p", "3000"]
