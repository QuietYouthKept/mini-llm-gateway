# Official ``python:3.12-slim`` manifest digest verified on 2026-10-10.
# Keep builder and runtime on the same immutable base image.
FROM python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS builder

ARG SOURCE_DATE_EPOCH=0
WORKDIR /build
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir "uv==0.11.23" \
    && uv sync --frozen --no-dev --extra production --no-install-project \
    && find /build/.venv -depth -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +

FROM python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime

ARG SOURCE_DATE_EPOCH=0
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 10001 gateway \
    && useradd --uid 10001 --gid gateway --no-create-home --shell /usr/sbin/nologin gateway

COPY --from=builder --chown=gateway:gateway /build/.venv /app/.venv
RUN --mount=type=bind,source=app,target=/source/app,ro \
    --mount=type=bind,source=config,target=/source/config,ro \
    --mount=type=bind,source=migrations/postgresql,target=/source/migrations,ro \
    mkdir -p /app/app /app/config /app/migrations/postgresql \
    && cp -R /source/app/. /app/app/ \
    && cp -R /source/config/. /app/config/ \
    && cp -R /source/migrations/. /app/migrations/postgresql/ \
    && chown -R gateway:gateway /app/app /app/config /app/migrations/postgresql \
    && find /app/app /app/config /app/migrations -depth \
        -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/live', timeout=2)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
