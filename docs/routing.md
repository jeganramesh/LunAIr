# Routing

LunAIr routes on two independent layers:

* **Model layer** — which model answers (the `model` field, or an `auto/*` alias).
* **Endpoint layer** — which endpoint of that model serves it.

An **endpoint** is a `(provider, upstream model, region, tier)` tuple with its
own pricing and capabilities. Routing operates on endpoints, which is what
makes load balancing, price/latency sorting, failover and data-policy routing
possible.

## Configuration

```yaml
models:
  gpt-4o-mini:
    endpoints:
      - provider: openai
        model: openai/gpt-4o-mini
        price_in: 0.15        # USD per 1M prompt tokens
        price_out: 0.60
        context: 128000
        api_key: os.environ/OPENAI_API_KEY
      - provider: azure
        model: azure/gpt-4o-mini
        price_in: 0.14
        price_out: 0.55
        region: eu
        zdr: true
        weight: 2.0

routing:
  strategy: priority            # default strategy
  auto_weights:                 # weights for the `auto` strategy
    cost: 0.35
    latency: 0.30
    success: 0.25
    load: 0.10
  aliases:
    auto/cheap:   { strategy: cost_optimized,    candidates: ["gemini-2.0-flash", "gpt-4o-mini"] }
    auto/fast:    { strategy: latency_optimized, candidates: ["groq-llama", "gemini-2.0-flash"] }
    auto/balanced:{ strategy: auto,              candidates: ["gpt-4o-mini", "gemini-2.0-flash"] }
```

The legacy `model_list:` shape still works — each entry becomes a single
endpoint, so existing deployments are unchanged.

## Strategies

| Strategy | Picks |
|---|---|
| `priority` | first endpoint in config order |
| `weighted` | weighted random by `weight` |
| `round_robin` | rotate across endpoints |
| `random` | uniform random |
| `least_used` | fewest in-flight requests |
| `p2c` | power-of-two-choices load balancing |
| `cost_optimized` | cheapest blended price |
| `latency_optimized` | lowest observed p95 latency |
| `throughput_optimized` | lowest observed average latency |
| `lkgp` | most recent successful endpoint (last-known-good) |
| `cache_optimized` | pin a prompt prefix to the endpoint that served it |
| `auto` | multi-factor score (cost, latency, success, load) |

## Provider preferences

Pass a `provider` object in the request body:

```json
{
  "model": "gpt-4o-mini",
  "messages": [{"role": "user", "content": "hi"}],
  "provider": {
    "order": ["azure", "openai"],
    "only": ["azure", "openai"],
    "ignore": ["groq"],
    "sort": "price",
    "max_price": 0.5,
    "zdr": true,
    "data_collection": "deny",
    "allow_fallbacks": true
  }
}
```

`only`/`ignore`/`zdr`/`data_collection` filter the candidate set; `max_price`
refuses the request if nothing is affordable; `order` and `sort` set the order.

## Model fallback arrays

```json
{"model": "gpt-4o-mini", "models": ["gemini-2.0-flash", "groq-llama"], "messages": [...]}
```

If the primary model's endpoints all fail, the fallback models' endpoints are
tried in order.

## Request lifecycle

1. Resolve `model` → candidate endpoints (expanding `auto/*` aliases).
2. Apply provider preferences.
3. Append `models` fallback endpoints.
4. Drop endpoints whose provider is unconfigured or whose breaker is open.
5. Order by the selected strategy.
6. Try each endpoint in order; the first success wins, and
   `X-LUNAIR-Fallback-From` is set only when a genuine failover happened.

Response headers report the decision: `X-LUNAIR-Endpoint`, `X-LUNAIR-Provider`,
`X-LUNAIR-Model`, `X-LUNAIR-Strategy`, `X-LUNAIR-Requested`.

## Telemetry

`reliability/stats.py` keeps a rolling, in-process window of latency, success
and in-flight counts per endpoint. It is a routing *hint*, not a source of
truth: each replica scores from its own recent traffic, which is sufficient for
load balancing and degrades gracefully. A shared (Redis) variant can be layered
on later without changing callers.
