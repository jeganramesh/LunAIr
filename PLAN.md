LUNAIR — PLAN.md

LLM Unified Native AI Inference Router

---

1. Project Overview

LUNAIR is a self-hostable, OpenAI-compatible LLM gateway that unifies multiple AI providers behind a single API. It solves provider lock-in, outage resilience, cost visibility, PII leakage, prompt injection attacks, and redundant inference costs for companies using multiple AI models.

One-line pitch: Clone, deploy in 5 minutes. Go gateway handles edge traffic, FastAPI core handles LLM orchestration. Route across OpenAI, Gemini, and Groq with auto-fallback, PII redaction, injection blocking, semantic caching, and unified balance view.

Scope: 3-day MVP. Go gateway (production path) + FastAPI core (AI logic) + React dashboard. Docker Compose deployment.

Architecture principle: Go is the actual production gateway. FASTAPI_ONLY is a development mode for fast iteration without rebuilding the Go binary.

---

2. Architecture

```
Client / OpenAI SDK
        │
        ▼
┌──────────────────────────────────────────────────────┐
│  GO GATEWAY (Production path)                        │
│  - API-key auth                                      │
│  - Rate limiting (token bucket + Redis)              │
│  - Circuit breaker (per provider)                    │
│  - Request routing                                   │
│  - SSE streaming passthrough                         │
│  - Metrics (Prometheus)                              │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────┐
│  FASTAPI CORE (AI orchestration)                     │
│  - LiteLLM provider abstraction                      │
│  - Provider fallback chain (A → B → C)               │
│  - PII detection + redaction                         │
│  - Prompt injection detection                        │
│  - Semantic cache (Redis)                            │
│  - Cost / token / latency tracking                   │
│  - Analytics + balance aggregation                   │
└──────────────────────────────────────────────────────┘
        │
        ├── OpenAI
        ├── Gemini
        └── Groq

┌──────────────────────────────────────────────────────┐
│  REACT DASHBOARD (Vite + Tailwind + Recharts)        │
│  - Calls FastAPI core via API_URL                    │
└──────────────────────────────────────────────────────┘
```

Two modes (env var GATEWAY_MODE):

· go (production): Client → Go Gateway → FastAPI Core → Providers.
· fastapi_only (development): Client → FastAPI Core → Providers.

Only one config value changes. Both paths return identical OpenAI-compatible responses.

Request lifecycle (production mode):

1. Client sends OpenAI-format request to Go gateway
2. Go validates API key against Redis (or FastAPI /internal/validate)
3. Go checks rate limit (token bucket in Redis)
4. Go checks circuit breaker state per provider
5. Go forwards to FastAPI with trusted headers (X-LUNAIR-Verified: true, X-LUNAIR-Key-Id)
6. FastAPI runs injection scan → PII redaction → semantic cache check → LiteLLM with fallback
7. Response passes PII scan, cache store on MISS, usage logged to SQLite
8. FastAPI returns response; Go streams back to client via SSE
9. Go increments metrics; FastAPI updates balance cache

---

3. Why Two Layers

Go gateway strengths (latency-sensitive edge):

· Concurrency: goroutines handle 10K+ concurrent connections with predictable tail latency
· Reverse proxying: purpose-built for HTTP forwarding and SSE streaming
· Rate limiting: token bucket with Redis at sub-millisecond overhead
· Circuit breaker: per-provider isolation without blocking the event loop
· Low memory: ~14MB per process vs ~90MB for Python equivalents
· Single binary deploy: no runtime, no venv, no dependency hell

FastAPI core strengths (AI/business logic):

· LiteLLM: 100+ providers, built-in fallback, cost tracking, semantic caching backends
· Python AI ecosystem: redact-prompt, llm-firewall, septr, sentence-transformers
· Async API design: non-blocking calls to LLM providers
· Analytics: SQLite/Postgres queries for usage, cost, cache stats
· Rapid iteration: hot-reload for development

Interview signal: Two distinct engineering skill sets, distributed architecture thinking, and choosing the right tool per layer.

---

4. Highlighted Features (Differentiators)

Go Gateway — Production Edge

Production entry point. Handles API key auth, rate limiting (token bucket per key in Redis), per-provider circuit breaker, request routing, SSE streaming passthrough, and Prometheus metrics. Built with Gin. Uses httputil.ReverseProxy with FlushInterval: -1 for streaming-safe forwarding. Benchmark target: <10ms P99 overhead vs direct FastAPI path.

Unified Balance Viewer

Single dashboard panel showing real-time credit/balance across all connected providers. LUNAIR calls each provider's balance endpoint, normalizes to USD equivalent, displays remaining credits with progress bars. OpenRouter exposes GET /v1/credits returning remaining balance and lifetime spend. Refresh on a timer.

Token Usage & Cost Analytics

Every request logged with prompt tokens, completion tokens, reasoning tokens, cached tokens, total cost, latency, finish reason. React dashboard renders time-series charts via Recharts. Per-API-key usage attribution. LiteLLM's completion_cost() calculates cost per request.

Prompt Storing & Versioning

Logs store prompts/responses with configurable retention (default 30 days, hard cap 180 days, cascade delete). Prompt version metadata attached to logs. Raw prompt capture is opt-in, not default. Logs include DLP actions taken — Flag or Block, matched policy IDs, detection entries triggered.

Prompt Injection & Jailbreak Detection

Blocks prompt injection, jailbreak, and instruction override attacks before they reach any provider. FastAPI uses llm-firewall middleware with lexical heuristics, role-switch detection, hierarchical policy enforcement. Returns blocked, risk_score, threats. If risk_score > 0.7, blocked with 403 + audit log. One-line integration: app.add_middleware(LLMFirewallMiddleware).

Semantic Caching

Two levels: exact-match (hash of full request) and semantic (embedding similarity). Uses llm-cache-redis backed by Redis with similarity_threshold (default 0.90), ttl (default 3600s), and namespace. Measured: "Tell me about Docker" scores 0.9238 against "What is Docker?" — HIT at 0.90. Unrelated prompts score near zero. On HIT: X-LUNAIR-Cache: HIT. On MISS: provider called and response stored.

Security Implementation

PII detection/masking on prompts and responses — email, phone, Aadhaar, card, SSN, API keys, JWTs. Credentials stored in encrypted vault. septr provides one-line runtime security: create_septr(app, {"apiKey": os.environ["SEPTR_API_KEY"]}) with flags for promptInjection, pii, secrets, rateLimit, ssrf, bola. Zero-trust gateway sanitizes tool output payloads.

---

5. Tech Stack

Layer Technology Reason
Edge Gateway Go + Gin High-concurrency reverse proxy, rate limiting, circuit breaker, SSE streaming
AI Core FastAPI + Python LiteLLM, PII/injection middleware, semantic cache, analytics
LLM Abstraction LiteLLM 100+ providers, built-in retry/fallback, cost tracking, semantic caching
Database SQLite (MVP) → PostgreSQL Lightweight logging, zero config for MVP
Cache + Rate Limit Store Redis Shared state for Go rate limiter + FastAPI semantic cache
PII Detection redact-prompt Regex + NER, numbered placeholders, restore in responses
Injection Detection llm-firewall Pattern-based prompt injection detection with FastAPI middleware
Runtime Security septr One-line FastAPI middleware for PII, secrets, injection, rate limiting
Semantic Caching llm-cache-redis Redis-backed semantic cache with sentence-transformers embeddings
Metrics prometheus-fastapi-instrumentator + Go promhttp Unified Prometheus surface from both layers
Frontend TypeScript + React + Vite Fast dev server, type safety, mature ecosystem
Styling Tailwind CSS Utility-first, rapid UI without writing CSS files
Charts Recharts Composable React chart library, works well with Tailwind layouts
HTTP Client Native fetch or axios Fetch usage/stats from FastAPI core
Deployment Docker + Docker Compose Multi-service orchestration
Cloud Railway or Render Free tier, auto-deploy from Git

---

6. Frontend

Stack: TypeScript + React + Vite + Tailwind CSS + Recharts.

Why this stack: Vite gives instant hot reload and fast production builds. TypeScript gives type safety across API calls. Tailwind lets you build a clean dashboard without writing CSS files. Recharts renders React-native charts that compose well with Tailwind layouts.

Dashboard pages (single-page app, tabbed):

· Balance — card grid of provider balances (OpenAI, OpenRouter, Groq, DeepSeek). Each card shows remaining USD, progress bar against configured budget, last refreshed timestamp.
· Usage — Recharts <LineChart> for token consumption over time, <AreaChart> for cost trend, <BarChart> for provider distribution. Filter by provider, model, API key.
· Logs — table of recent requests: provider, model, tokens in/out, cost, latency, PII redacted, injection blocked, cache hit/miss, gateway mode. Highlight rows where PII was redacted or injection blocked.
· Cache — hit rate over time, total savings USD, average similarity score of hits.
· Health — circuit breaker state per provider, /health from both Go and FastAPI.
· Benchmark — Go gateway P50/P99 overhead vs fastapi_only mode, rendered from scripts/bench.sh output.

API integration: VITE_API_URL env var points to FastAPI core (default http://localhost:8000). All data fetched via fetch to FastAPI endpoints.

Folder structure:

```
dashboard/
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/
│   │   └── client.ts
│   ├── components/
│   │   ├── BalanceCard.tsx
│   │   ├── UsageChart.tsx
│   │   ├── LogsTable.tsx
│   │   ├── CacheStats.tsx
│   │   ├── ProviderHealth.tsx
│   │   └── BenchmarkPanel.tsx
│   ├── pages/
│   │   ├── Balance.tsx
│   │   ├── Usage.tsx
│   │   ├── Logs.tsx
│   │   └── Health.tsx
│   └── types/
│       └── api.ts
├── index.html
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
└── package.json
```

Docker Compose service: dashboard runs npm run dev -- --host on port 5173 (dev) or npm run build && npx serve dist on port 3000 (prod).

---

7. Implementation

Go Gateway (Production Edge)

Task Detail
Scaffold gateway/main.go, gateway/middleware/, gateway/proxy/
Gin server POST /v1/chat/completions, GET /health, GET /metrics
API key auth middleware Validate against Redis cache; fallback to FastAPI /internal/validate
Rate limit middleware Token bucket per API key in Redis, RPM + TPM
Circuit breaker middleware Per-provider failure counter in Redis; open after N failures
Reverse proxy httputil.ReverseProxy to FASTAPI_URL, inject X-LUNAIR-Verified: true and X-LUNAIR-Key-Id
SSE streaming FlushInterval: -1 for real-time token streaming
Metrics promhttp.Handler() at /metrics
Mode switch Read GATEWAY_MODE; if fastapi_only, skip Go entirely (dev)
Test curl through Go proxy → verify headers + response + metrics

FastAPI Core (AI Orchestration)

Task Detail
Project scaffold pyproject.toml, app/ structure, .env handling
FastAPI app main.py with /v1/chat/completions, /v1/models, /v1/balance, /v1/usage, /health, /metrics, /internal/validate
LiteLLM Router config.yaml with OpenAI, Gemini, Groq model groups
Fallback chain fallbacks=[{"gpt-4o-mini": ["gemini-2.0-flash", "groq/llama-3.3-70b"]}]
Request/response schema Pydantic models matching OpenAI format
Trust middleware If X-LUNAIR-Verified: true, skip auth/rate limit
Injection detection llm-firewall middleware. Block if result.blocked or risk_score > 0.7
PII detection redact-prompt: email, phone, Aadhaar, card, API keys
Prompt redaction Replace with [EMAIL_1], [PHONE_1]; instruct LLM to preserve placeholders
Response scan Scan response for leaked PII before returning
Semantic cache LLMCache(redis_url=..., similarity_threshold=0.90, ttl=3600, namespace="lunair")
Auto-routing auto/cheap → cheapest model; auto/fast → lowest latency
CORS Enable CORS for dashboard origin
SQLite logging requests table: id, key_id, model, provider, tokens_in, tokens_out, reasoning_tokens, cached_tokens, cost, latency_ms, ttft_ms, fallback_from, pii_redacted, injection_blocked, cache_hit, cache_similarity, gateway_mode, finish_reason
Cost calculation LiteLLM completion_cost()
Balance cache Background task fetches provider balances every 5 min
Test Prompt with email + phone + "Ignore all previous instructions" → verify block, redact, cache

Reliability + Ops + Dashboard

Task Detail
Circuit breaker (FastAPI) Per-provider isolation when running in fastapi_only mode
Multi-key rotation Round-robin API keys per provider on 429
Prometheus metrics Unified surface; both Go and FastAPI expose counters
React dashboard Vite scaffold, Tailwind config, Recharts components for Balance/Usage/Logs/Health/Benchmark
Docker Compose gateway + fastapi + dashboard + redis services
Config file config.yaml for providers, routing, budgets, injection, cache, gateway mode
Benchmark scripts/bench.sh comparing Go gateway vs fastapi_only with 100 concurrent requests
Deploy template railway.json / render.yaml with three services (Go + FastAPI + Dashboard)
README Architecture diagram, quick start, env vars, API examples, benchmark results, screenshots

---

8. File Structure

```
lunair/
├── gateway/                     # Go edge gateway
│   ├── main.go
│   ├── config.go
│   ├── middleware/
│   │   ├── auth.go
│   │   ├── ratelimit.go
│   │   ├── circuitbreaker.go
│   │   └── metrics.go
│   ├── proxy/
│   │   └── reverse.go
│   └── go.mod
├── app/                         # FastAPI core
│   ├── main.py
│   ├── config.py
│   ├── models.py
│   ├── router_engine.py
│   ├── pii.py
│   ├── injection.py
│   ├── semantic_cache.py
│   ├── circuit_breaker.py
│   ├── rate_limit.py
│   ├── logging_db.py
│   ├── balance.py
│   ├── metrics.py
│   ├── trust.py
│   └── litellm_router.py
├── dashboard/                   # React + Vite + Tailwind + Recharts
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/client.ts
│   │   ├── components/
│   │   │   ├── BalanceCard.tsx
│   │   │   ├── UsageChart.tsx
│   │   │   ├── LogsTable.tsx
│   │   │   ├── CacheStats.tsx
│   │   │   ├── ProviderHealth.tsx
│   │   │   └── BenchmarkPanel.tsx
│   │   ├── pages/
│   │   │   ├── Balance.tsx
│   │   │   ├── Usage.tsx
│   │   │   ├── Logs.tsx
│   │   │   └── Health.tsx
│   │   └── types/api.ts
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── package.json
├── shared/
│   └── models.py
├── scripts/
│   └── bench.sh
├── config.yaml
├── docker-compose.yml
├── gateway.Dockerfile
├── fastapi.Dockerfile
├── dashboard.Dockerfile
├── railway.json / render.yaml
├── requirements.txt / pyproject.toml
├── .env.example
└── README.md
```

---

9. Configuration Example (config.yaml)

```yaml
gateway:
  mode: "go"                    # "go" (production) or "fastapi_only" (dev)
  fastapi_url: "http://fastapi:8000"
  listen_port: 8080
  rate_limit:
    rpm_per_key: 60
    tpm_per_key: 100000
  circuit_breaker:
    failure_threshold: 3
    cooldown_seconds: 60

model_list:
  - model_name: gpt-4o-mini
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
  - model_name: gemini-2.0-flash
    litellm_params:
      model: gemini/gemini-2.0-flash
      api_key: os.environ/GEMINI_API_KEY
  - model_name: groq-llama
    litellm_params:
      model: groq/llama-3.3-70b
      api_key: os.environ/GROQ_API_KEY

router_settings:
  fallbacks:
    - gpt-4o-mini: ["gemini-2.0-flash", "groq-llama"]

routing:
  auto/cheap: ["gemini-2.0-flash", "gpt-4o-mini"]
  auto/fast: ["groq-llama", "gemini-2.0-flash"]

balance:
  refresh_interval_seconds: 300
  providers:
    - name: openai
      endpoint: https://api.openai.com/v1/dashboard/billing/credit_grants
    - name: openrouter
      endpoint: https://openrouter.ai/api/v1/credits
    - name: deepseek
      endpoint: https://api.deepseek.com/user/balance

budgets:
  default_monthly_usd: 50
  warn_at_pct: 80
  block_at_pct: 100

security:
  pii_redaction: true
  pii_types: ["EMAIL", "PHONE", "SSN", "CREDIT_CARD", "API_KEY"]
  provider_allowlist: ["openai", "gemini", "groq"]
  store_prompts: false
  log_retention_days: 30
  injection_detection: true
  injection_sensitivity: "high"
  injection_risk_threshold: 0.7

semantic_cache:
  enabled: true
  redis_url: os.environ/REDIS_URL
  similarity_threshold: 0.90
  ttl_seconds: 3600
  namespace: "lunair"
  exclude_agent_keys: true

logging:
  store_prompts_in_spend_logs: true
```

---

10. API Surface

Endpoint Layer Method Purpose
/v1/chat/completions Go → FastAPI POST OpenAI-compatible chat
/v1/models Go → FastAPI GET List available models + auto-routes
/v1/balance Go → FastAPI GET Unified provider balance (USD)
/v1/usage Go → FastAPI GET Per-key usage summary
/health Go + FastAPI GET Provider health + circuit breaker state
/metrics Go + FastAPI GET Prometheus metrics
/internal/validate FastAPI POST Key validation endpoint for Go

Request example:

```json
{
  "model": "auto/cheap",
  "messages": [{"role": "user", "content": "Summarize this email: john@acme.com"}]
}
```

Blocked request (injection): 403 with {"error": "prompt_injection_detected", "risk_score": 0.95, "threats": ["INSTRUCTION_OVERRIDE"]}.

Response headers:

· X-LUNAIR-Gateway: go
· X-LUNAIR-Provider: gemini
· X-LUNAIR-Model: gemini-2.0-flash
· X-LUNAIR-Fallback-From: gpt-4o-mini
· X-LUNAIR-PII-Redacted: 1
· X-LUNAIR-Injection-Blocked: 0
· X-LUNAIR-Cache: MISS
· X-LUNAIR-Cost-USD: 0.00012
· X-LUNAIR-Tokens-In: 24
· X-LUNAIR-Tokens-Out: 18

Balance response:

```json
{
  "openai": {"balance_usd": 12.40, "lifetime_spend_usd": 47.60},
  "openrouter": {"credits_remaining_usd": 8.20, "credits_purchased_usd": 25.00},
  "groq": {"balance_usd": null, "note": "usage-based, no prepaid balance"},
  "total_remaining_usd": 20.60,
  "last_refreshed": "2026-10-08T12:00:00Z"
}
```

---

11. What to Skip (3-Day Constraint)

· Multi-tenant org/team hierarchy
· Billing integration (Stripe)
· ML-based DLP classifiers beyond regex + NER
· Full Grafana stack
· Stateful PII placeholder restoration (redact permanently for MVP)
· Real-time WebSocket balance streaming (poll every 5 min)
· Trustrail output safety validation for XSS/path traversal
· ForceField cloud gateway sync
· Sophisticated Go proxy features (mTLS, advanced load balancing)
· Custom embeddings model for semantic cache (use default all-MiniLM-L6-v2)
· React SSR / Next.js (Vite SPA is enough)
· Component library (shadcn, MUI) — use plain Tailwind for speed

---

12. Resume Talking Points

Built LUNAIR, a two-layer AI gateway with a Go edge proxy (API-key auth, rate limiting, circuit breaker, SSE streaming, Prometheus metrics) and a FastAPI core (LiteLLM orchestration, provider fallback, PII redaction, prompt-injection detection, semantic caching, cost/token analytics). Unified OpenAI, Gemini, and Groq behind a single OpenAI-compatible API with auto-combo routing (auto/cheap, auto/fast) and a unified provider balance viewer. Built a React + Vite + Tailwind + Recharts dashboard for live balance, usage analytics, cache hit rate, and security events. Benchmarked Go gateway vs direct FastAPI path with 100 concurrent requests. Deployed on Railway with Docker Compose.

Interview answers this enables:

· "How do you handle provider outages?" → Per-provider circuit breaker at Go edge + fallback chain in FastAPI core
· "How do you prevent data leakage?" → redact-prompt PII detection with numbered placeholders + response scan + opt-in prompt logging with retention
· "How do you block prompt injection?" → llm-firewall middleware pre-inference scan with risk_score > 0.7 threshold
· "How do you control AI costs?" → Per-request logging + budget guardrails + auto/cheap routing + unified balance viewer + semantic caching
· "Why Go + FastAPI?" → Go for latency-sensitive edge (auth, rate limit, circuit break, streaming) with predictable tail latency at 10K+ connections; FastAPI for AI orchestration where the Python ecosystem is unmatched
· "How do the two layers talk?" → Go injects trusted headers (X-LUNAIR-Verified: true, X-LUNAIR-Key-Id); FastAPI skips auth/rate limit when trusted
· "Why React + Vite over Streamlit?" → Type safety, real charting with Recharts, and a production-quality UI that ships as static assets
· "How do you reduce latency?" → Semantic caching with Redis serves nearest-neighbor responses above 0.90 similarity, avoiding provider round trips
· "What did you benchmark?" → Go gateway P99 overhead vs fastapi_only mode under 100 concurrent requests; Go maintains sub-10ms overhead while FastAPI alone spikes under load





Final stack:
```
Go + Gin
FastAPI + LiteLLM
PostgreSQL
Redis
React + TypeScript + Vite
Tailwind + Recharts
Docker Compose
```
That is strong enough to stop architecture changes and start implementation.

# LunAIR — Monorepo Structure

You are in: `~/LunAIR/` (L capital, un lowercase, AIR capital)

---

## 1. Complete Monorepo Tree

```
LunAIR/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                    # lint + test all services
│   │   ├── docker.yml                # build images
│   │   └── security.yml              # secret scan, dep audit
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── CODEOWNERS
│
├── .gitignore
├── .dockerignore
├── .editorconfig
├── .env.example                      # committed (no real values)
├── .env                              # IGNORED — never commit
├── .gitattributes
├── LICENSE                           # MIT or Apache-2.0
├── README.md
├── SECURITY.md                       # vulnerability disclosure policy
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── CHANGELOG.md
├── Makefile                          # top-level dev commands
├── docker-compose.yml
├── docker-compose.dev.yml            # hot-reload overrides
├── docker-compose.prod.yml           # prod overrides
│
├── gateway/                          # Go edge gateway
│   ├── cmd/
│   │   └── lunair-gateway/
│   │       └── main.go
│   ├── internal/
│   │   ├── config/
│   │   │   └── config.go
│   │   ├── middleware/
│   │   │   ├── auth.go
│   │   │   ├── ratelimit.go
│   │   │   ├── circuitbreaker.go
│   │   │   ├── metrics.go
│   │   │   └── recover.go
│   │   ├── proxy/
│   │   │   ├── reverse.go
│   │   │   └── streaming.go
│   │   ├── redis/
│   │   │   └── client.go
│   │   ├── fastapi/
│   │   │   └── client.go            # calls FastAPI /internal/validate
│   │   └── health/
│   │       └── health.go
│   ├── pkg/
│   │   └── logger/
│   │       └── logger.go
│   ├── tests/
│   │   ├── middleware_test.go
│   │   └── proxy_test.go
│   ├── go.mod
│   ├── go.sum
│   ├── Dockerfile
│   └── README.md
│
├── app/                              # FastAPI AI core
│   ├── src/
│   │   └── lunair/
│   │       ├── __init__.py
│   │       ├── main.py
│   │       ├── config.py
│   │       ├── api/
│   │       │   ├── __init__.py
│   │       │   ├── deps.py
│   │       │   └── routes/
│   │       │       ├── chat.py
│   │       │       ├── models.py
│   │       │       ├── balance.py
│   │       │       ├── usage.py
│   │       │       ├── health.py
│   │       │       ├── metrics.py
│   │       │       └── internal.py  # /internal/validate
│   │       ├── core/
│   │       │   ├── litellm_router.py
│   │       │   ├── router_engine.py
│   │       │   ├── trust.py
│   │       │   └── security_headers.py
│   │       ├── security/
│   │       │   ├── pii.py
│   │       │   ├── injection.py
│   │       │   └── secrets.py
│   │       ├── cache/
│   │       │   └── semantic.py
│   │       ├── reliability/
│   │       │   ├── circuit_breaker.py
│   │       │   └── key_rotation.py
│   │       ├── observability/
│   │       │   ├── metrics.py
│   │       │   ├── logging.py
│   │       │   └── tracing.py
│   │       ├── db/
│   │       │   ├── base.py
│   │       │   ├── models.py
│   │       │   ├── queries.py
│   │       │   └── session.py
│   │       ├── schemas/
│   │       │   ├── chat.py
│   │       │   ├── balance.py
│   │       │   ├── usage.py
│   │       │   └── common.py
│   │       ├── services/
│   │       │   ├── balance_service.py
│   │       │   ├── usage_service.py
│   │       │   └── retention_service.py
│   │       └── utils/
│   │           ├── hashing.py
│   │           └── time.py
│   ├── migrations/                   # Alembic
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 0001_initial.py
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── conftest.py
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── Dockerfile
│   └── README.md
│
├── dashboard/                        # React + Vite + Tailwind + Recharts
│   ├── public/
│   │   └── favicon.svg
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── index.css
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   └── endpoints.ts
│   │   ├── components/
│   │   │   ├── Layout/
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   └── Topbar.tsx
│   │   │   ├── BalanceCard.tsx
│   │   │   ├── UsageChart.tsx
│   │   │   ├── LogsTable.tsx
│   │   │   ├── CacheStats.tsx
│   │   │   ├── ProviderHealth.tsx
│   │   │   └── BenchmarkPanel.tsx
│   │   ├── pages/
│   │   │   ├── Balance.tsx
│   │   │   ├── Usage.tsx
│   │   │   ├── Logs.tsx
│   │   │   ├── Cache.tsx
│   │   │   ├── Health.tsx
│   │   │   └── Benchmark.tsx
│   │   ├── hooks/
│   │   │   ├── useApi.ts
│   │   │   └── useInterval.ts
│   │   ├── types/
│   │   │   └── api.ts
│   │   └── utils/
│   │       └── format.ts
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   ├── package.json
│   ├── package-lock.json             # committed
│   ├── .env.example
│   ├── .env                          # IGNORED
│   ├── Dockerfile
│   └── README.md
│
├── infra/
│   ├── docker/
│   │   ├── postgres/
│   │   │   └── init.sql              # extensions, roles
│   │   └── nginx/
│   │       └── nginx.conf            # optional prod reverse proxy
│   ├── railway/
│   │   └── railway.json
│   ├── render/
│   │   └── render.yaml
│   └── terraform/                    # optional, for later
│       └── README.md
│
├── scripts/
│   ├── bench.sh                      # Go vs FastAPI benchmark
│   ├── seed_db.py                    # dev seed data
│   ├── generate_api_key.py
│   └── refresh_matview.sql
│
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── deployment.md
│   ├── security.md
│   ├── benchmark.md
│   └── diagrams/
│       ├── architecture.png
│       └── request-flow.png
│
├── config/
│   ├── config.yaml                   # committed (no secrets)
│   ├── config.dev.yaml
│   └── config.prod.yaml
│
└── tests/
    ├── e2e/
    │   ├── test_chat_flow.py
    │   ├── test_injection_block.py
    │   ├── test_pii_redaction.py
    │   └── test_cache_hit.py
    └── load/
        └── k6-script.js
```

---

## 2. Public Repository Rules

**`.gitignore` (root):**

```gitignore
# Secrets — NEVER commit
.env
.env.*
!.env.example
*.pem
*.key
*.crt
secrets/
credentials/
*.secret

# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/
dist/
build/

# Node
node_modules/
dist/
.vite/
*.local

# Go
gateway/bin/
*.test
*.out
vendor/

# Databases
*.db
*.sqlite
*.sqlite3
postgres_data/

# Logs
*.log
logs/

# OS / Editor
.DS_Store
Thumbs.db
.idea/
.vscode/
*.swp

# Docker
docker-compose.override.yml

# Benchmarks (optional)
scripts/bench-results.json
```

**`.dockerignore` (root):**

```
.git
.github
.env
.env.*
!.env.example
node_modules
.venv
__pycache__
*.log
docs
tests
infra
```

**`.env.example` (committed — placeholder values only):**

```bash
# Database
DATABASE_URL=postgresql+asyncpg://lunair:CHANGE_ME@postgres:5432/lunair
POSTGRES_USER=lunair
POSTGRES_PASSWORD=CHANGE_ME
POSTGRES_DB=lunair

# Redis
REDIS_URL=redis://redis:6379/0

# Providers — REPLACE WITH YOUR KEYS LOCALLY
OPENAI_API_KEY=sk-REPLACE_ME
GEMINI_API_KEY=REPLACE_ME
GROQ_API_KEY=REPLACE_ME

# Security
SEPTR_API_KEY=REPLACE_ME

# Gateway
GATEWAY_MODE=go
FASTAPI_URL=http://fastapi:8000
GATEWAY_PORT=8080

# Frontend
VITE_API_URL=http://localhost:8080
```

**`SECURITY.md` (required for public repo):**

- Supported versions
- How to report a vulnerability (private email, not GitHub issue)
- Response timeline (48h acknowledge, 7d fix)
- Do not open public issues for security bugs
- Do not include real API keys, PII, or customer data in any issue, PR, or test

**`CONTRIBUTING.md`:**

- Branch naming: `feat/`, `fix/`, `chore/`, `docs/`
- Commit convention: Conventional Commits
- PR must pass CI (lint + test + secret scan)
- No secrets in code, tests, or fixtures — use env vars
- No real provider calls in CI; use mocks or recorded fixtures
- Do not commit `.env`, keys, tokens, or production data

**`LICENSE`:** MIT or Apache-2.0. Pick one.

**`.github/workflows/security.yml`:**

- Run `gitleaks` on every push
- Run `trufflehog` on every PR
- Fail build if any secret is detected
- Run `pip-audit`, `npm audit`, `govulncheck`

**`.github/CODEOWNERS`:**

```
*                       @your-handle
/gateway/               @your-handle
/app/                   @your-handle
/dashboard/             @your-handle
/infra/                 @your-handle
/.github/               @your-handle
```

**`CHANGELOG.md`:** Keep a Changelog format, updated on every release.

**What must NEVER be in a public repo:**

| Category | Rule |
|---|---|
| API keys | Never. Use `.env` locally, platform secrets in prod |
| `.env` files | Never. Only `.env.example` |
| Database dumps | Never. Seed scripts only |
| Customer data | Never. Synthetic fixtures only |
| Private keys / certs | Never |
| Internal URLs / IPs | Never |
| Production logs | Never |
| Personal info | Never |
| ML model weights | Never (link to registry instead) |
| `node_modules/`, `.venv/` | Never |
| `postgres_data/`, `redis_data/` | Never |

---

## 3. Top-Level `Makefile`

```makefile
.PHONY: help up down logs build test lint fmt clean

help:
	@echo "make up      - start all services"
	@echo "make down    - stop all services"
	@echo "make logs    - tail logs"
	@echo "make build   - rebuild images"
	@echo "make test    - run all tests"
	@echo "make lint    - lint all services"
	@echo "make fmt     - format all services"
	@echo "make clean   - remove volumes"

up:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

test:
	cd app && pytest
	cd gateway && go test ./...
	cd dashboard && npm test

lint:
	cd app && ruff check .
	cd gateway && golangci-lint run
	cd dashboard && npm run lint

fmt:
	cd app && ruff format .
	cd gateway && gofmt -w .
	cd dashboard && npm run format

clean:
	docker compose down -v
```

---

## 4. Root `docker-compose.yml`

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./infra/docker/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  fastapi:
    build: ./app
    env_file: .env
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
    ports: ["8000:8000"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s

  gateway:
    build: ./gateway
    env_file: .env
    depends_on:
      fastapi: { condition: service_healthy }
    ports: ["8080:8080"]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:8080/health"]
      interval: 10s

  dashboard:
    build: ./dashboard
    env_file: .env
    depends_on:
      gateway: { condition: service_started }
    ports: ["5173:5173"]

volumes:
  postgres_data:
  redis_data:
```

---

## 5. Setup Commands

```bash
cd LunAIR/

# 1. Copy env template
cp .env.example .env
# Edit .env → add real API keys locally

# 2. Init Go module (gateway)
cd gateway && go mod tidy && cd ..

# 3. Init Python env (app)
cd app && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]" && cd ..

# 4. Init Node (dashboard)
cd dashboard && npm install && cd ..

# 5. Run Alembic migration
cd app && alembic upgrade head && cd ..

# 6. Start everything
make up

# 7. Verify
curl http://localhost:8080/health
open http://localhost:5173
```

---

## 6. Rules to Enforce Before Making Repo Public

- [ ] `.env` never committed (verify with `git log --all -- .env`)
- [ ] Run `gitleaks detect --source .` → zero findings
- [ ] Run `trufflehog filesystem .` → zero findings
- [ ] All API keys in `.env.example` are placeholders
- [ ] `LICENSE` present
- [ ] `SECURITY.md` present
- [ ] `CONTRIBUTING.md` present
- [ ] `CODE_OF_CONDUCT.md` present
- [ ] `README.md` has setup steps that work from scratch
- [ ] CI passes on a clean clone
- [ ] No screenshots containing real API keys
- [ ] No database dumps or fixtures with real data
- [ ] `.gitignore` covers all secret patterns
- [ ] Branch protection enabled on `main` (require PR review)
- [ ] Dependabot enabled for Go, Python, npm
- [ ] GitHub secret scanning enabled
- [ ] Repository description + topics set: `llm-gateway`, `fastapi`, `go`, `semantic-cache`, `ai-infra`