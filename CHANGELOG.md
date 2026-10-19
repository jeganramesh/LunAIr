# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-19

Hardening pass: closes the security, correctness and reliability gaps found in
review, and makes several config-only features real.

### Security
- **Gateway now authenticates callers.** The Go edge resolves the API key (via
  the core's `/internal/validate`, cached in Redis) and forwards the resolved
  key id. It is no longer an unauthenticated open proxy.
- **Trusted-header path requires a shared secret.** The core only honours
  `X-LUNAIR-Verified` when `X-LUNAIR-Gateway-Secret` matches
  `GATEWAY_SHARED_SECRET`; otherwise it fails closed.
- **Development auth bypass is gated** behind `DEV_AUTH_BYPASS` (default off).
- **Key-management API** (`/v1/keys`) added, gated behind `LUNAIR_ADMIN_KEY`.

### Added
- Per-key **rate limiting** (RPM/TPM, Redis-backed, fail-closed) enforced before
  the provider call.
- Per-key **monthly budgets** enforced with `warn`/`block` thresholds.
- **Streaming requests are now logged and costed** (usage is captured via
  `stream_options.include_usage`).
- **Automatic partition provisioning** so `requests` keeps partitioning past the
  initial months; default-partition row count is alerted on boot.
- **Request IDs** (`X-Request-Id`) on every request and response.
- `/ready` readiness endpoint (checks Postgres and Redis); `/health` now reports
  dependency status and circuit-breaker state.
- **Leader election** for background jobs (Postgres advisory lock) so replicas
  do not duplicate retention/refresh work.
- Gateway server timeouts and a real, config-driven **circuit breaker** that
  short-circuits known-bad providers.

### Fixed
- `X-LUNAIR-Fallback-From` no longer fires on `auto/*` alias expansion — only on
  a genuine failover.
- OpenAI parameters (`n`, `top_p`, penalties, `seed`, `tools`, `response_format`,
  …) are forwarded instead of silently dropped; tool-calling and multimodal
  messages are accepted.
- Provider balance lookups now send credentials, and read the latest snapshot
  per provider with `DISTINCT ON` instead of scanning all history.
- Retries no longer multiply (Router retries disabled; the candidate loop owns
  failover).
- `daily_usage` refreshes concurrently (non-blocking).
- Docker build no longer fails when `scripts/bench-results.json` is absent.

### Changed
- Dependencies pinned with upper bounds; `fastapi` held `<0.116` for
  instrumentator compatibility. Added `ruff.toml` for deterministic linting.

## [0.1.0] - 2026-10-08

### Added
- Monorepo scaffold with Go gateway, FastAPI core, and PostgreSQL/Redis infrastructure.
- FastAPI core with LiteLLM routing, auto/cheap, auto/fast routes, and trust middleware.
- Go reverse proxy edge with Gin and real-time streaming passthrough.
- PostgreSQL partitioned request tracking schema.
