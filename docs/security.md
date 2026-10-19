# Security

## Trust boundary

The gateway and FastAPI communicate over an internal Docker network. The
gateway resolves the caller's API key and marks requests it forwards with:

```
X-LUNAIR-Verified: true
X-LUNAIR-Key-Id: <resolved client key id>
X-LUNAIR-Gateway-Secret: <GATEWAY_SHARED_SECRET>
```

FastAPI's `verify_trust_or_auth` honours the trusted path **only when the
shared secret matches**. Without a matching secret it returns `401`, so a
client that can reach port 8000 cannot impersonate the gateway by setting the
header itself.

- `GATEWAY_SHARED_SECRET` must be set to the same value on the gateway and the
  core. If it is unset the core refuses the trusted-header path (fail closed).
- `X-LUNAIR-Key-Id` is set by the gateway from the **resolved** key, not from
  the client, so a caller can no longer choose their own `key_id`.
- The gateway authenticates every `/v1/*` request before forwarding: it
  resolves the `Authorization: Bearer` key through the core's
  `/internal/validate` (itself gated on the shared secret) and caches the result
  in Redis for `GATEWAY_AUTH_CACHE_SECONDS`.

Deployment guidance:

- Publish **8080 only**. Keep 8000 on the internal network in production;
  Compose binds 8000 to the host for development convenience only.
- Put TLS termination and any WAF in front of 8080.

## API keys

`api_keys.key_hash` stores a SHA-256 hex digest, never the key itself.

Validation flow for direct (non-gateway) clients:

1. Extract the `Bearer` token from `Authorization`.
2. SHA-256 the token, hex-encode.
3. Look up `key_hash` where `is_active = true`.

Row fields: `id`, `key_hash`, `name`, `rpm_limit` (60), `tpm_limit` (100000),
`monthly_budget_usd` (50), `is_active`, timestamps.

### Key management

`/v1/keys` (create / list / update / revoke) is gated behind `LUNAIR_ADMIN_KEY`.
When that variable is unset the endpoints return `404` and are effectively
disabled, so key management cannot be exposed by accident. Plaintext keys are
returned exactly once, at creation.

```bash
curl -X POST http://localhost:8000/v1/keys \
  -H "X-LUNAIR-Admin-Key: $LUNAIR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"team-a","rpm_limit":120,"monthly_budget_usd":100}'
```

### Development bypass

`DEV_AUTH_BYPASS` (default `false`) enables a local-only shortcut that accepts
any token beginning with `sk-`/`lunair_` or equal to `test-key` when no row
matches. It is **off by default** and must stay off outside development.

## Credential handling

- `.env` is gitignored; `.env.example` carries placeholders only.
- Provider keys are referenced in `config/config.yaml` as
  `os.environ/OPENAI_API_KEY` and resolved at read time, so no secret is
  committed.
- Container environment variables are visible via `docker inspect`. On a shared
  host, prefer Docker secrets or a mounted credentials file.
- The gateway and FastAPI both load the same `.env` via `env_file`, so every
  service receives every provider key — including ones it does not use. Scope
  `env_file` per service if that matters for your threat model.

## Limits and budgets

- **Rate limiting**: `gateway.rate_limit` (`rpm_per_key`, `tpm_per_key`) is
  enforced per key in Redis. If Redis is unreachable the limiter fails **closed**
  by default (`RATE_LIMIT_FAIL_CLOSED`); set it to `false` to fail open.
- **Budgets**: each key's `monthly_budget_usd` (or `budgets.default_monthly_usd`)
  is enforced against the current month's spend, with `warn_at_pct` / `block_at_pct`
  thresholds. Over-budget requests get `402`.

## SQL injection

All database access goes through SQLAlchemy ORM models or parameterised `text()`
queries. No user input is interpolated into SQL strings.

## PII and prompt injection

`config/config.yaml` declares the policy (`security.pii_redaction`,
`injection_detection`, …) and the `pii_events` / `injection_events` tables
exist, but the enforcement middleware is still **not implemented**. Prompts and
responses currently reach providers unredacted and unscanned. `store_prompts:
false` is honoured in the sense that no prompt text is persisted.

## Input validation

Pydantic v2 schemas validate every request body before handler code runs. The
chat schema is deliberately permissive (`extra="allow"`) so new OpenAI
parameters do not break clients; only a known-safe parameter set is forwarded
upstream.

## Error handling

Provider exceptions are truncated to 300 characters before being returned to
clients (`summarize_error` in `app/src/lunair/api/routes/chat.py`). Request-log
write failures are counted (`lunair_logging_failures_total`) and logged rather
than swallowed silently.

## Reporting

Do not open a public issue for a security bug. See
[../SECURITY.md](../SECURITY.md) for the disclosure process.

## Pre-publication checklist

```bash
git log --all -- .env                        # must be empty
gitleaks detect --source .                   # zero findings
trufflehog filesystem .                      # zero findings
```

Also confirm `.env.example` still holds placeholders only, and that no real keys
appear in test fixtures or committed screenshots.
