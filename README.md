# LunAIR 🚀
**LLM Unified Native AI Inference Router**

LunAIR is a self-hostable, OpenAI-compatible LLM gateway unifying multiple AI providers (OpenAI, Gemini, Groq) behind a single resilient edge gateway.

---

## 🏛 Architecture

- **Go Gateway (Edge)**: High-concurrency reverse proxy, token-bucket rate limiting, circuit breakers, and streaming passthrough with sub-millisecond overhead.
- **FastAPI Core (AI Engine)**: LiteLLM provider fallback chain, prompt injection blocking, PII redaction, semantic caching, and analytics.
- **PostgreSQL**: Partitioned request logging and materialized usage analytics.
- **Redis**: Shared rate limiter state and semantic cache.
- **React Dashboard**: Real-time token usage, cost analytics, and provider balances.

---

## 🚀 Quick Start

### 1. Configure Environment
```bash
cp .env.example .env
# Edit .env with your provider API keys
```

### 2. Launch with Docker Compose
```bash
# full stack (Go gateway :8080 + FastAPI :8000)
docker compose --profile gateway up --build -d
```

### 3. Send a Request
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "auto/cheap",
    "messages": [{"role": "user", "content": "Hello LunAIR!"}]
  }'
```

---

## ⚙️ Switching Gateway Modes

`GATEWAY_MODE` accepts two values (also read from `config/config.yaml`):

| Mode | Value | Traffic path |
|------|-------|--------------|
| Production (default) | `go` | Client → Go gateway `:8080` → FastAPI `:8000` → providers |
| Development | `fastapi_only` | Client → FastAPI `:8000` → providers (Go edge skipped) |

Toggle it with the compose profile:

```bash
# fastapi_only — Go gateway is not started (default)
docker compose up -d

# go — full stack including the gateway
docker compose --profile gateway up -d
```

Both paths return identical OpenAI-compatible responses.

---

## 🩺 Verify the Stack

```bash
curl http://localhost:8080/health   # gateway
curl http://localhost:8000/health   # fastapi core
curl http://localhost:8080/v1/models
curl http://localhost:8080/metrics  # prometheus counters
```

Database migrations run automatically on FastAPI container start.

