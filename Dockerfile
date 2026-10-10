# Official ``python:3.12-slim`` manifest digest verified on 2026-10-10.
# Keep builder and runtime on the same immutable base image.
FROM python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS builder

WORKDIR /build
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir "uv==0.11.23" \
    && uv sync --frozen --no-dev --extra production --no-install-project

FROM python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 10001 gateway \
    && useradd --uid 10001 --gid gateway --no-create-home --shell /usr/sbin/nologin gateway

COPY --from=builder --chown=gateway:gateway /build/.venv /app/.venv
COPY --chown=gateway:gateway app ./app
COPY --chown=gateway:gateway config ./config
COPY --chown=gateway:gateway migrations/postgresql ./migrations/postgresql

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/live', timeout=2)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
