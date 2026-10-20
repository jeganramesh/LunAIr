"""Prometheus metrics for the FastAPI core.

Names are prefixed ``lunair_`` and deliberately do not collide with the Go
gateway's ``lunair_gateway_*`` series, so a single scrape target can expose
both layers without metric-name clashes.
"""

from prometheus_client import Counter, Histogram

REQUESTS_TOTAL = Counter(
    "lunair_requests_total",
    "Chat completions served, by provider, model and outcome.",
    ["provider", "model", "status"],
)

FALLBACK_TOTAL = Counter(
    "lunair_fallback_total",
    "Fallbacks triggered, by originating and serving model.",
    ["from_model", "to_model"],
)

REQUEST_LATENCY = Histogram(
    "lunair_request_latency_seconds",
    "End-to-end chat completion latency in seconds.",
    ["provider"],
)

BALANCE_REFRESH = Counter(
    "lunair_balance_refresh_total",
    "Provider balance refresh attempts.",
    ["provider", "outcome"],
)

USAGE_QUERY = Counter(
    "lunair_usage_query_total",
    "Dashboard usage queries served.",
    ["endpoint"],
)

LOGGING_FAILURES = Counter(
    "lunair_logging_failures_total",
    "Request-log writes that failed (analytics may be incomplete).",
)

RATE_LIMITED = Counter(
    "lunair_rate_limited_total",
    "Requests rejected by the rate limiter.",
    ["key_id"],
)

BUDGET_BLOCKED = Counter(
    "lunair_budget_blocked_total",
    "Requests rejected because a budget limit was reached.",
    ["key_id"],
)

PII_REDACTED = Counter(
    "lunair_pii_redacted_total",
    "PII entities redacted from prompts.",
)

INJECTION_BLOCKED = Counter(
    "lunair_injection_blocked_total",
    "Requests blocked by prompt-injection detection.",
)

CACHE_HITS = Counter("lunair_cache_hits_total", "Response cache hits.")
CACHE_MISSES = Counter("lunair_cache_misses_total", "Response cache misses.")


def observe_completion(
    provider: str,
    model: str,
    status: str,
    latency_seconds: float = 0.0,
    fallback_from: str | None = None,
) -> None:
    """Record one chat completion outcome."""
    REQUESTS_TOTAL.labels(provider=provider, model=model, status=status).inc()
    REQUEST_LATENCY.labels(provider=provider).observe(latency_seconds)
    if fallback_from:
        FALLBACK_TOTAL.labels(from_model=fallback_from, to_model=model).inc()


def observe_balance_refresh(provider: str, outcome: str) -> None:
    BALANCE_REFRESH.labels(provider=provider, outcome=outcome).inc()
