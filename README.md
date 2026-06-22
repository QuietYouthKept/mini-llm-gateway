# mini-llm-gateway

A lightweight, local-first LLM Gateway that demonstrates why model calls should be
centralized behind a gateway instead of being scattered across business code as
provider-specific if-else logic.

Built with FastAPI, SQLite, and YAML config. Runs entirely locally with mock/fake
providers — no real API keys needed.

## Why This Exists

When teams integrate LLMs directly into business logic, every service ends up
repeating the same provider-switching, fallback, retry, rate-limit, and budget
tracking code. This project shows how a gateway layer solves that by providing:

- **Model profiles** — abstract model descriptions decoupled from providers
- **Provider routing** — pick the best provider based on priority, latency, or cost
- **Fallback chains** — degrade gracefully when a provider fails or times out
- **Request logging** — audit every call with full attempt history
- **API key auth** — authenticate clients at the gateway, not at each provider
- **Rate limiting & token budget** — enforce usage controls in one place

## MVP Scope

- `POST /v1/chat` — gateway-debuggable chat endpoint
- `POST /v1/chat/completions` — OpenAI-compatible chat completions
- `GET /v1/requests/{request_id}` — request audit trail
- `GET /health` — health check
- Mock/fake providers (no real LLM API keys required)
- YAML static config + SQLite runtime state
- Docker Compose for one-command startup

## Quick Start

### Windows

```cmd
pip install -e ".[dev]"
dev.bat
```

另开一个终端验证：
```cmd
curl http://localhost:8000/health
test.bat
```

### macOS / Linux

```bash
pip install -e ".[dev]"
make dev
curl http://localhost:8000/health
make test
```

### Docker

```bash
docker compose up --build
```
