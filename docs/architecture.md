# Architecture

## Two layers, one API

```
Client / OpenAI SDK
        │
        ▼
┌──────────────────────────────────────────────────────┐
│  GO GATEWAY  (port 8080)                              │
│  - Reverse proxy with SSE passthrough                 │
│  - Trusted-header injection                          │
│  - Prometheus metrics                                │
│  - Graceful shutdown                                 │
└──────────────────────────────────────────────────────┘
        │  X-LUNAIR-Verified: true
        │  X-LUNAIR-Key-Id: <client key id>
        ▼
┌──────────────────────────────────────────────────────┐
│  FASTAPI CORE  (port 8000)                            │
│  - Trust middleware (auth skip for gateway traffic)   │
│  - Credential preflight                              │
│  - Auto-routing (auto/cheap, auto/fast)              │
│  - LiteLLM router with provider fallback             │
│  - SSE + non-streaming responses                     │
│  - Request logging to PostgreSQL                     │
└──────────────────────────────────────────────────────┘
        │
        ├── OpenAI   (gpt-4o-mini)
        ├── Gemini   (gemini-2.0-flash)
        └── Groq     (llama-3.3-70b)
```

## Why two layers

**Go** owns latency-sensitive edge work: connection concurrency, streaming
forwarding, and low-overhead request handling. A single static binary with no
runtime dependency.

**FastAPI** owns AI logic, where the Python ecosystem has no real substitute —
LiteLLM's provider abstraction is the whole reason this layer exists.

The split means you can iterate on AI logic without rebuilding the Go binary.

## Modes

`GATEWAY_MODE` selects the active path. Both return identical
OpenAI-compatible responses.

| Mode | Traffic path | How to run |
|------|--------------|------------|
| `go` | Client → gateway :8080 → FastAPI :8000 | `docker compose --profile gateway up -d` |
| `fastapi_only` | Client → FastAPI :8000 | `docker compose up -d` |

The gateway sits behind the compose profile `gateway`, so a plain
`docker compose up -d` never starts it. This is deliberate: it makes the dev
loop (edit FastAPI, reload, no Go rebuild) the default.

In `fastapi_only` mode the gateway binary, if started anyway, refuses to proxy
and returns `404` with `{"error":{"type":"gateway_disabled"}}`.

## Request lifecycle

Production (`go`) mode:

1. Client POSTs an OpenAI-format body to `:8080/v1/chat/completions`.
2. Gateway sets `X-LUNAIR-Verified: true` and `X-LUNAIR-Key-Id`, then forwards
   to FastAPI. `httputil.ReverseProxy` with `FlushInterval: -1` keeps SSE
   chunks unbuffered.
3. `verify_trust_or_auth` sees the verified header and skips the Bearer
   lookup. A client hitting FastAPI directly gets `401`.
4. Credential preflight drops providers without real API keys. If none of the
   requested model's candidates are configured, respond `503` naming the
   missing env vars.
5. `resolve_intent` expands `auto/cheap` and `auto/fast` into ordered
   candidate lists from `config/config.yaml`.
6. Candidates are tried in priority order. The first success wins; the request
   records `fallback_from` when it was not the originally requested model.
7. A `Request` row is written to PostgreSQL with provider, tokens, cost and
   latency. Logging failures are swallowed so analytics never break a call.
8. Response returns with `X-LUNAIR-Provider`, `X-LUNAIR-Model`,
   `X-LUNAIR-Cost-USD` and, when relevant, `X-LUNAIR-Fallback-From`.

## Streaming

`stream: true` returns `StreamingResponse` with `Content-Type:
text/event-stream`. Chunks are forwarded as they arrive and terminated with
`data: [DONE]`. Stream errors are emitted as a final SSE error frame rather
than a broken connection.

Cost is reported as `0.000000` on streaming responses because usage is not
known until the stream completes.

## Storage

**PostgreSQL 16** — `requests` is range-partitioned monthly on `created_at`,
with a `requests_default` catch-all partition. Indexes cover
`(key_id, created_at DESC)`, `(provider, created_at DESC)` and `cache_hit`.
The `pii_events` and `injection_events` tables are indexed on `request_id`.

Alembic migrations run in the container entrypoint (`alembic upgrade head`),
so a fresh volume comes up with the full schema and no manual step.

**Redis 7** — reserved for the Phase 2 rate limiter and semantic cache. The Go
gateway pings it on boot and logs a warning rather than exiting if it is
unavailable.

## Repository layout

```
LunAIR/
├── app/                  FastAPI AI core
│   ├── src/lunair/
│   │   ├── main.py           app factory, /health, /v1/echo
│   │   ├── config.py         settings + config.yaml + credential preflight
│   │   ├── api/routes/       chat.py, models.py
│   │   ├── core/             litellm_router.py, router_engine.py, trust.py
│   │   ├── db/               base.py (engine), models.py (schema)
│   │   └── schemas/          chat.py, common.py
│   ├── migrations/       Alembic
│   ├── Dockerfile
│   └── docker-entrypoint.sh
├── gateway/              Go edge
│   ├── cmd/lunair-gateway/main.go
│   ├── internal/config/      env configuration
│   ├── internal/health/      /health
│   ├── internal/middleware/  metrics
│   ├── internal/proxy/       reverse.go, streaming.go
│   ├── internal/redis/       client
│   ├── pkg/logger/
│   ├── tests/
│   └── Dockerfile
├── config/config.yaml    providers, routing, fallbacks, budgets, cache
├── infra/docker/postgres/init.sql
├── tests/unit/           pytest suite
└── docker-compose.yml
```

## Configuration

Two layers, and it matters which wins:

- **Environment / `.env`** — credentials, connection strings, ports. Handled by
  pydantic-settings.
- **`config/config.yaml`** — provider list, fallback chains, `auto/*` routing,
  budgets, security policy, cache settings. No secrets; API keys are referenced
  as `os.environ/VAR_NAME` and resolved at read time.

Editing `config.yaml` requires a FastAPI restart; it is read once and cached.