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
docker compose up --build
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
LunAIR supports two modes via the `GATEWAY_MODE` environment variable or `config/config.yaml`:
- `go` (default / production): Traffic flows through the Go proxy on port 8080 to FastAPI on port 8000.
- `fastapi_only` (dev): Clients communicate directly with FastAPI on port 8000.
