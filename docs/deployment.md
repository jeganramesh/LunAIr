# Deployment

## Requirements

- Docker 20.10+ with Compose v2
- Ports free: `5432`, `6379`, `8000`, `8080`
- Real provider API keys for at least one of OpenAI, Gemini or Groq

## Quick start

```bash
cp .env.example .env
# edit .env — set provider keys
docker compose --profile gateway up --build -d
```

Verify:

```bash
curl http://localhost:8080/health   # gateway
curl http://localhost:8000/health   # fastapi
```

Confirm credentials actually loaded — `providers_ready` should be at least 1:

```bash
curl -s http://localhost:8000/health | grep -o '"providers_ready":[0-9]*'
```

## Services

| Service | Image | Port | Depends on |
|---------|-------|------|------------|
| `postgres` | `postgres:16-alpine` | 5432 | — |
| `redis` | `redis:7-alpine` | 6379 | — |
| `fastapi` | built from `app/Dockerfile` | 8000 | postgres + redis healthy |
| `gateway` | built from `gateway/Dockerfile` | 8080 | fastapi healthy (profile `gateway`) |

Startup is gated on health checks, so FastAPI only starts once Postgres accepts
queries and Redis answers `PING`, and the gateway only starts once FastAPI
serves `/health`.

## Environment variables

### Credentials

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENAI_API_KEY` | one of | Serves `gpt-4o-mini` |
| `GEMINI_API_KEY` | one of | Serves `gemini-2.0-flash` |
| `GROQ_API_KEY` | one of | Serves `groq-llama` |

Placeholder values (`REPLACE_ME`, `CHANGE_ME`) are treated as missing. See
[api.md](api.md#health) for how this surfaces.

### Security

| Variable | Default | Notes |
|----------|---------|-------|
| `GATEWAY_SHARED_SECRET` | insecure dev default | **Change this.** Must match on gateway and core; the core refuses the trusted-header path otherwise |
| `LUNAIR_ADMIN_KEY` | unset | Unlocks `/v1/keys`; leave unset to disable key management |
| `DEV_AUTH_BYPASS` | `false` | Local-only auth shortcut. Keep `false` outside development |
| `RATE_LIMIT_FAIL_CLOSED` | `true` | Reject requests when the rate limiter (Redis) is unavailable |
| `BUDGET_ENFORCEMENT` | `true` | Enforce per-key monthly budgets |

### Limits & budgets

| Variable | Default | Notes |
|----------|---------|-------|
| `UPSTREAM_TIMEOUT_SECONDS` | `30` | Per-attempt provider timeout |
| `REQUEST_TIMEOUT_SECONDS` | `120` | End-to-end request budget |
| `PARTITION_MONTHS_AHEAD` | `3` | Months of `requests` partitions kept provisioned |

### Infrastructure

| Variable | Default | Notes |
|----------|---------|-------|
| `POSTGRES_USER` | `lunair` | |
| `POSTGRES_PASSWORD` | `CHANGE_ME` | **Change this.** Compose substitutes it into `DATABASE_URL` |
| `POSTGRES_DB` | `lunair` | |
| `DATABASE_URL` | composed by Compose | Overridden per-service to point at `postgres:5432` |
| `REDIS_URL` | composed by Compose | Overridden to `redis://redis:6379/0` |

### Gateway

| Variable | Default | Notes |
|----------|---------|-------|
| `GATEWAY_MODE` | `go` | `go` or `fastapi_only` |
| `FASTAPI_URL` | `http://fastapi:8000` | Gateway's upstream |
| `GATEWAY_PORT` | `8080` | |

### Application

| Variable | Default | Notes |
|----------|---------|-------|
| `CONFIG_PATH` | `config/config.yaml` | Set to `/app/config/config.yaml` in the image |
| `VITE_API_URL` | `http://localhost:8080` | Dashboard, when built |

## Database migrations

The FastAPI image runs `alembic upgrade head` from `app/docker-entrypoint.sh`
before starting uvicorn. A fresh volume gets the full schema, including
monthly `requests` partitions, with no manual step.

Run manually:

```bash
docker compose exec fastapi alembic upgrade head
```

Inspect state:

```bash
docker compose exec postgres psql -U lunair -d lunair -c '\dt'
docker compose exec postgres psql -U lunair -d lunair -c 'SELECT * FROM alembic_version;'
```

Expect 10 relations: `api_keys`, `requests` (partitioned), `requests_default`,
two monthly partitions, `pii_events`, `injection_events`,
`balance_snapshots`, `budgets`, `alembic_version`.

## Switching modes

```bash
# fastapi_only — Go gateway not started
docker compose up -d

# go — full stack
docker compose --profile gateway up -d
```

Move between them freely; they share the same Postgres and Redis volumes.

To keep the gateway running but disable proxying, set
`GATEWAY_MODE=fastapi_only` in `.env`. The gateway then serves `/health` and
`/metrics` and returns `404` with `gateway_disabled` on `/v1/*`.

## Make targets

| Target | Action |
|--------|--------|
| `make up` | start without the gateway |
| `make up-go` | start everything |
| `make down` | stop, keep volumes |
| `make clean` | stop and delete volumes |
| `make build` | rebuild images |
| `make logs` | tail all logs |
| `make test` | Python and Go tests |
| `make lint` | ruff + gofmt check |
| `make fmt` | ruff format + gofmt |

Go tooling runs in a `golang:1.22-alpine` container because host Go is often
older than the gateway's `go.mod` requires. Module downloads are cached in the
`lunair-gomodcache` volume.

Python tests need the venv: `app/.venv/bin/python -m pip install -e "app[dev]"`.

## Development

FastAPI hot reload, no Go rebuild:

```bash
docker compose up -d
docker compose exec fastapi uvicorn lunair.main:app --reload --host 0.0.0.0 --port 8000
```

## Troubleshooting

**`failed to read dockerfile`** — the service has no `Dockerfile`. Rebuild with
`docker compose build`.

**Gateway returns `404 gateway_disabled`** — `GATEWAY_MODE=fastapi_only`. Either
switch the value or start with `--profile gateway`.

**`503` on chat completions** — no provider credentials. Check
`providers_ready` in `/health`, then confirm the key is not a placeholder in
`.env`.

**`502` on chat completions** — credentials exist but every candidate failed.
`detail` names the model and the truncated last error. Provider-side causes:
expired key, revoked quota, model not enabled for the account.

**FastAPI restart loop, migration errors** — inspect with
`docker compose logs fastapi`. Usually a stale volume from an older schema:
`make clean` and rebuild.

**Port already allocated** — another Postgres or Redis holds 5432/6379. Stop it,
or change the host-side port in `docker-compose.yml`.

**Connection refused on `:8080`** — the gateway is behind a compose profile.
Start with `docker compose --profile gateway up -d`.

## Production notes

- Set a real `POSTGRES_PASSWORD`.
- Do not publish port 8000 to the internet. Clients should reach the gateway on
  8080 only — see [security.md](security.md).
- Terminate TLS in front of the gateway.
- `requests` is partitioned monthly. Add future partitions ahead of time:
  `CREATE TABLE requests_y2026m12 PARTITION OF requests FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');`
- Restart policies are `unless-stopped`, so containers survive host reboots.