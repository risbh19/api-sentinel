FROM ghcr.io/astral-sh/uv:0.13.9 AS uv
FROM python:3.13.18-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache
COPY src/ src/
ENV PATH="/app/.venv/bin:${PATH}" PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
CMD ["uvicorn","api_sentinel.main:create_app","--factory","--host","0.0.0.0","--port","8000","--no-access-log","--no-proxy-headers","--no-server-header"]
