FROM ghcr.io/astral-sh/uv:0.13.9 AS uv
FROM python:3.12.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache --python /usr/local/bin/python
COPY src/ ./src/
USER 65532:65532
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "api_sentinel.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header", "--no-proxy-headers"]
