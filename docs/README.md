# LunAIR Documentation

Self-hostable, OpenAI-compatible LLM gateway that unifies OpenAI, Gemini and Groq
behind a single resilient edge gateway.

## Documents

| Doc | Contents |
|-----|----------|
| [architecture.md](architecture.md) | Two-layer design, request lifecycle, component layout |
| [api.md](api.md) | Every endpoint, headers, status codes, curl examples |
| [deployment.md](deployment.md) | Docker Compose, environment variables, migrations, troubleshooting |
| [security.md](security.md) | Trust model, auth flow, credential handling |
| [benchmark.md](benchmark.md) | Go gateway vs direct FastAPI overhead |

Diagrams: [architecture.svg](diagrams/architecture.svg) and
[request-flow.svg](diagrams/request-flow.svg).

## Status

Phase 1 (core gateway + AI core) is implemented and verified. Phase 2 (PII
redaction, injection detection, semantic cache, rate limiting, Prometheus
metrics on the FastAPI side) is planned in [PLAN.md](../PLAN.md).

Implemented today:

- Go edge gateway: reverse proxy with SSE passthrough, trusted-header injection,
  `/health`, Prometheus metrics
- FastAPI core: LiteLLM router with provider fallback, `auto/*` routing,
  `/v1/chat/completions` (streaming and non-streaming), `/v1/models`, `/v1/echo`
- Trust middleware: gateway-verified requests bypass auth; direct clients need a
  Bearer key
- Provider credential preflight: placeholder keys fail fast with `503`
- PostgreSQL with monthly partitioning on `requests`, plus an Alembic migration
  that runs automatically on container start
- Redis for rate-limit and cache state