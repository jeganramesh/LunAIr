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
# Set GATEWAY_SHARED_SECRET to a random value (must match on gateway + core)
```

> **Required:** the core only trusts requests forwarded by the gateway when
> `GATEWAY_SHARED_SECRET` matches on both services. It ships with an insecure
> development default — change it before any real deployment. See
> [docs/security.md](docs/security.md).

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

---

## 🔐 Security, limits & budgets

- **Authentication** happens at the gateway; the core trusts forwarded requests
  only with a matching `GATEWAY_SHARED_SECRET`.
- **Rate limits** (`rpm_per_key`, `tpm_per_key`) and **monthly budgets** are
  enforced per key before the provider call. Over-limit requests get `429`;
  over-budget requests get `402`.
- **Key management** is available at `/v1/keys` when `LUNAIR_ADMIN_KEY` is set.
- Streaming responses are logged and costed just like non-streaming ones.
- Every request carries an `X-Request-Id` for tracing.

See [docs/security.md](docs/security.md) for the full model.

---

## 🧭 Routing

LunAIr routes on two layers: the **model** (which model answers) and the
**endpoint** (which provider/region/tier serves it). A model can have several
endpoints, each with its own pricing.

- **Strategies**: `priority`, `weighted`, `round_robin`, `random`, `least_used`,
  `p2c`, `cost_optimized`, `latency_optimized`, `throughput_optimized`, `lkgp`,
  `cache_optimized`, `auto`.
- **`auto/*` aliases** pick a strategy per alias (`auto/cheap`, `auto/fast`,
  `auto/balanced`, …); `auto` scores endpoints on cost, latency, success and load.
- **Provider preferences** per request: `order`, `only`, `ignore`, `sort`,
  `max_price`, `zdr`, `data_collection`, `allow_fallbacks`.
- **Model fallbacks**: pass `"models": [...]` to fail over across models.
- **Guardrails**: PII redaction (restorable) and prompt-injection detection run
  before the provider call.
- **Caching & compression**: tenant-scoped response cache and a safe prompt
  compression tier.

See [docs/routing.md](docs/routing.md) for configuration and the request lifecycle.

