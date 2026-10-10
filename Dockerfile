# ``python:3.12-slim`` currently resolves to this Docker Hub manifest digest.
# Update both occurrences through the release dependency update workflow.
FROM python@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65 AS builder

WORKDIR /build
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir "uv==0.11.23" \
    && uv sync --frozen --no-dev --extra production --no-install-project

FROM python@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65 AS runtime

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 10001 gateway \
    && useradd --uid 10001 --gid gateway --no-create-home --shell /usr/sbin/nologin gateway

COPY --from=builder --chown=gateway:gateway /build/.venv /app/.venv
COPY --chown=gateway:gateway app ./app
COPY --chown=gateway:gateway config ./config

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/live', timeout=2)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
