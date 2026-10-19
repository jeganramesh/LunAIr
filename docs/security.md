# Security

## Trust boundary

The gateway and FastAPI communicate over an internal Docker network. The
gateway marks requests it forwards with:

```
X-LUNAIR-Verified: true
X-LUNAIR-Key-Id: <client key id>
```

FastAPI's `verify_trust_or_auth` treats that header as proof the request came
from the gateway and skips per-request authentication.

> **This is the most important constraint in the deployment.** FastAPI does not
> verify who set `X-LUNAIR-Verified`. It is a claim, not a proof. If port 8000
> is reachable by anything untrusted, that client can set the header itself and
> bypass authentication entirely.

Therefore:

- Publish **8080 only**. Keep 8000 on the internal network.
- Compose binds 8000 to the host for development convenience. Remove that
  mapping before any real deployment:

  ```yaml
  fastapi:
    ports: []   # or delete the ports block entirely
    expose:
      - "8000"
  ```

- Put TLS termination and any WAF in front of 8080.

The same applies to `X-LUNAIR-Key-Id`: the gateway forwards a client-supplied
value, so a caller can choose their own `key_id` and it lands unverified in the
`requests` table. The Phase 2 auth middleware is what fixes this by hashing the
real key and resolving the id server-side.

## API keys

`api_keys.key_hash` stores a SHA-256 hex digest, never the key itself.

Validation flow for direct (non-gateway) clients:

1. Extract the `Bearer` token from `Authorization`.
2. SHA-256 the token, hex-encode.
3. Look up `key_hash` where `is_active = true`.

Row fields: `id`, `key_hash`, `name`, `rpm_limit` (60), `tpm_limit` (100000),
`monthly_budget_usd` (50), `is_active`, timestamps.

### Development bypass

`app/src/lunair/core/trust.py` accepts any token starting with `sk-` or
`lunair_`, or the literal `test-key`, when no matching row exists. This keeps
local development frictionless.

**This bypass is unconditional — it is not gated on an environment flag.** Do not
ship it as-is. Before production, wrap the branch so it only applies when
`settings.debug` is true or an explicit `DEV_AUTH_BYPASS` env var is set.

### Generating a key

```bash
python -c "import hashlib,secrets; k='lunair_'+secrets.token_urlsafe(32); print(k); print(hashlib.sha256(k.encode()).hexdigest())"
```

Insert the digest into `api_keys`, give the plaintext to the client, discard it
from your shell history.

## Credential handling

- `.env` is gitignored; `.env.example` carries placeholders only.
- Provider keys are referenced in `config/config.yaml` as
  `os.environ/OPENAI_API_KEY` and resolved at read time, so no secret is
  committed.
- Container environment variables are visible via `docker inspect`. On a shared
  host, prefer Docker secrets or a mounted credentials file.
- Compose injects `POSTGRES_PASSWORD` into `DATABASE_URL` for the FastAPI
  service. Rotating the password requires updating both together.

The gateway and FastAPI both load the same `.env` via `env_file`, so every
service receives every provider key — including ones it does not use. Scope
`env_file` per service if that matters for your threat model.

## SQL injection

All database access goes through SQLAlchemy ORM models. No string-built SQL
exists in the codebase.

## Injection and PII (Phase 2, not yet implemented)

`config/config.yaml` already declares the policy:

```yaml
security:
  pii_redaction: true
  pii_types: ["EMAIL", "PHONE", "SSN", "CREDIT_CARD", "API_KEY"]
  injection_detection: true
  injection_risk_threshold: 0.7
  store_prompts: false
  log_retention_days: 30
```

The `pii_events` and `injection_events` tables exist and the `requests` table
carries `pii_redacted` and `injection_blocked` flags — but no middleware reads
this config yet. Prompts and responses currently reach providers unredacted and
unscanned. See [PLAN.md](../PLAN.md) Phase 2 before exposing this to
untrusted users.

`store_prompts: false` is honoured only in the sense that no prompt text is
persisted: `requests` logs token counts and cost, not content.

## Input validation

Pydantic v2 schemas validate every request body before handler code runs.
`model` and `messages` are required; malformed bodies return `422`. Unknown
fields are ignored rather than rejected, which keeps OpenAI SDK compatibility
when new parameters are added upstream.

CORS is currently `allow_origins=["*"]` with `allow_credentials=True`. That
combination is rejected by browsers, but it still signals an open policy. Scope
it to the dashboard origin before production.

## Error handling

Provider exceptions are truncated to 300 characters before being returned to
clients (`summarize_error` in `app/src/lunair/api/routes/chat.py`). This keeps
SDK and debug banners — which can contain key fragments — out of responses.

`record_request_in_db` swallows all exceptions. Analytics failures never break a
served request, but they are also invisible. Worth monitoring once Phase 2
adds metrics.

## Reporting

Do not open a public issue for a security bug. See
[../SECURITY.md](../SECURITY.md) for the disclosure process.

## Pre-publication checklist

```bash
git log --all -- .env                        # must be empty
gitleaks detect --source .                   # zero findings
trufflehog filesystem .                     # zero findings
```

Also confirm `.env.example` still holds placeholders only, and that no real keys
appear in test fixtures or committed screenshots.