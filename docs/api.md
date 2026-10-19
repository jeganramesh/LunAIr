# API Reference

All endpoints speak the OpenAI wire format. Requests and responses are
`application/json` unless noted.

Base URLs:

- Gateway: `http://localhost:8080`
- FastAPI direct: `http://localhost:8000` (bypasses the gateway, requires a Bearer key)

## Authentication

Two paths, distinguished by `X-LUNAIR-Verified`:

| Caller | Header | Result |
|--------|--------|--------|
| Through gateway | injected by the gateway | auth skipped, `key_id` from `X-LUNAIR-Key-Id` |
| Direct to FastAPI | `Authorization: Bearer <key>` | key hashed (SHA-256) and looked up in `api_keys` |

Requests arriving without either get `401` and
`{"detail":"Missing Bearer API key in Authorization header"}`.

> Do not send `X-LUNAIR-Verified: true` yourself. FastAPI does not verify the
> caller's origin for that header, so anyone who can reach port 8000 can
> impersonate the gateway. Port 8000 must stay internal — see
> [security.md](security.md).

## `GET /health`

Available on both layers.

```bash
curl http://localhost:8080/health
curl http://localhost:8000/health
```

FastAPI response:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "gateway_mode": "go",
  "details": {
    "fastapi_url": "http://fastapi:8000",
    "providers": {
      "openai": {"configured": false, "env_var": "OPENAI_API_KEY", "model": "openai/gpt-4o-mini"},
      "gemini": {"configured": false, "env_var": "GEMINI_API_KEY", "model": "gemini/gemini-2.0-flash"},
      "groq":   {"configured": false, "env_var": "GROQ_API_KEY",   "model": "groq/llama-3.3-70b"}
    },
    "unconfigured_providers": {
      "openai": "OPENAI_API_KEY",
      "gemini": "GEMINI_API_KEY",
      "groq": "GROQ_API_KEY"
    },
    "providers_ready": 0,
    "providers_total": 3
  }
}
```

`providers_ready` counts providers holding a real, non-placeholder key. This is
the fastest way to confirm credentials loaded correctly.

Gateway response:

```json
{"status":"ok","component":"gateway","mode":"go","fastapi_url":"http://fastapi:8000","uptime_s":33}
```

## `GET /v1/models`

Lists configured models plus `auto/*` pseudo-models.

```bash
curl http://localhost:8080/v1/models
```

```json
{
  "object": "list",
  "data": [
    {"id": "gpt-4o-mini",      "object": "model", "created": 1791484177, "owned_by": "openai"},
    {"id": "gemini-2.0-flash", "object": "model", "created": 1791484177, "owned_by": "gemini"},
    {"id": "groq-llama",       "object": "model", "created": 1791484177, "owned_by": "groq"},
    {"id": "auto/cheap",       "object": "model", "created": 1791484177, "owned_by": "lunair"},
    {"id": "auto/fast",        "object": "model", "created": 1791484177, "owned_by": "lunair"}
  ]
}
```

## `POST /v1/chat/completions`

### Request

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `model` | string | required | `gpt-4o-mini`, `gemini-2.0-flash`, `groq-llama`, `auto/cheap`, `auto/fast` |
| `messages` | array | required | `{role, content, name?}` |
| `temperature` | float | `1.0` | |
| `top_p` | float | `1.0` | |
| `n` | int | `1` | |
| `stream` | bool | `false` | SSE when true |
| `stop` | string or array | null | |
| `max_tokens` | int | null | |
| `presence_penalty` | float | `0.0` | |
| `frequency_penalty` | float | `0.0` | |
| `user` | string | null | |

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "auto/cheap",
    "messages": [{"role": "user", "content": "Hello LunAIR!"}],
    "max_tokens": 64
  }'
```

### Response

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1791484200,
  "model": "gemini-2.0-flash",
  "choices": [
    {"index": 0, "message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}
  ],
  "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
}
```

### Response headers

| Header | Meaning |
|--------|---------|
| `X-LUNAIR-Provider` | provider that served the request |
| `X-LUNAIR-Model` | concrete model used |
| `X-LUNAIR-Requested` | model the caller asked for (e.g. `auto/cheap`) |
| `X-LUNAIR-Cost-USD` | cost from LiteLLM, six decimals. `0.000000` when streaming (the cost is still logged) |
| `X-LUNAIR-Fallback-From` | the first candidate, set **only** when a real failover occurred |
| `X-Request-Id` | correlation id (echoed from the request or generated) |

Through the gateway, `X-LUNAIR-Gateway: go` is also set.

### Streaming

Set `stream: true`. Chunks arrive as SSE frames terminated by `data: [DONE]`.

```bash
curl -N -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto/fast","messages":[{"role":"user","content":"Count to 5"}],"stream":true}'
```

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk",...}

data: [DONE]
```

A mid-stream failure is emitted as a final error frame, not a dropped
connection:

```json
{"error":{"message":"...","type":"stream_error"}}
```

### Status codes

| Code | Cause |
|------|-------|
| `200` | success (streaming or buffered) |
| `401` | direct call without a valid Bearer key, or gateway header without the shared secret |
| `402` | the key's monthly budget is exhausted |
| `422` | body failed schema validation |
| `429` | rate limit exceeded (RPM/TPM). `Retry-After` is set |
| `502` | every candidate provider failed. `detail` names the model and a truncated last error |
| `503` | no provider credentials configured. `detail` names the env vars to set |

The `503` case is deliberate: with placeholder keys in `.env`, every candidate
would otherwise fail individually and surface as an opaque `502` stack of
provider authentication errors.

## `POST /v1/echo`

Echoes the validated request body. Useful for schema checks and round-trip
testing without touching a provider.

```bash
curl -X POST http://localhost:8000/v1/echo \
  -H "Content-Type: application/json" \
  -d '{"model":"auto/cheap","messages":[{"role":"user","content":"hi"}]}'
```

## `GET /metrics`

Prometheus exposition format, gateway only.

```bash
curl http://localhost:8080/metrics
```

| Metric | Type | Labels |
|--------|------|--------|
| `lunair_gateway_requests_total` | counter | `method`, `path`, `status` |
| `lunair_gateway_latency_seconds` | histogram | `method`, `path` |

FastAPI metrics are Phase 2 work.

## Auto-routing

`auto/*` models expand to an ordered candidate list from
`config/config.yaml`:

| Requested | Candidate order |
|-----------|-----------------|
| `auto/cheap` | `gemini-2.0-flash`, then `gpt-4o-mini` |
| `auto/fast` | `groq-llama`, then `gemini-2.0-flash` |

Candidates are tried in order; the first success wins. Unconfigured providers
are removed from the list first, so a partially configured environment still
serves traffic through whatever is available.

Independent of `auto/*`, `config.yaml` declares a LiteLLM fallback chain
(`gpt-4o-mini` → `gemini-2.0-flash` → `groq-llama`) that operates inside the
LiteLLM router.

## `GET /ready`

Readiness probe. Returns `200` when Postgres and Redis are both reachable, else
`503`:

```json
{"ready": true, "dependencies": {"database": true, "redis": true}}
```

## Key management

Gated behind the `X-LUNAIR-Admin-Key` header (must equal `LUNAIR_ADMIN_KEY`).
When that variable is unset these endpoints return `404`.

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/keys` | Create a key; the plaintext is returned once |
| `GET` | `/v1/keys` | List keys (no secrets) |
| `PATCH` | `/v1/keys/{id}` | Update limits / budget / active state |
| `DELETE` | `/v1/keys/{id}` | Revoke (deactivate) a key |

```bash
curl -X POST http://localhost:8000/v1/keys \
  -H "X-LUNAIR-Admin-Key: $LUNAIR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"team-a","rpm_limit":120,"tpm_limit":200000,"monthly_budget_usd":100}'
```

## `POST /internal/validate`

Internal endpoint the gateway uses to resolve a Bearer key. Not part of the
public API; requires the `X-LUNAIR-Gateway-Secret` header.