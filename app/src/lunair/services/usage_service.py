from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from lunair.db.base import AsyncSessionLocal
from lunair.services.balance_service import collect_balances

RANGE_TO_DAYS = {
    "24h": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
}


async def query_usage(
    range_key: str = "7d",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    key_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Read the daily_usage materialized view with optional filters."""
    days = RANGE_TO_DAYS.get(range_key, 7)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    clauses = ["day >= :since"]
    params: Dict[str, Any] = {"since": since.date()}

    if provider:
        clauses.append("provider = :provider")
        params["provider"] = provider
    if model:
        clauses.append("model = :model")
        params["model"] = model
    if key_id:
        clauses.append("key_id = :key_id")
        params["key_id"] = key_id

    where = " AND ".join(clauses)
    sql = text(
        f"""
        SELECT day, provider, model, key_id,
               sum(tokens_in)      AS tokens_in,
               sum(tokens_out)     AS tokens_out,
               sum(total_cost)     AS cost,
               sum(request_count)  AS requests
        FROM daily_usage
        WHERE {where}
        GROUP BY day, provider, model, key_id
        ORDER BY day ASC, provider ASC
        """
    )

    rows = []
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(sql, params)
            rows = [dict(row) for row in result.mappings().all()]
    except Exception as err:
        return _empty_usage(range_key, days, f"{type(err).__name__}: {err}")

    for row in rows:
        row["day"] = row["day"].isoformat() if hasattr(row["day"], "isoformat") else row["day"]
        # Postgres sums over bigint come back as Decimal; normalize so the
        # dashboard receives JSON numbers rather than numeric strings.
        row["tokens_in"] = int(row["tokens_in"] or 0)
        row["tokens_out"] = int(row["tokens_out"] or 0)
        row["requests"] = int(row["requests"] or 0)
        row["cost"] = float(row["cost"] or 0.0)

    totals = {
        "tokens_in": sum(r["tokens_in"] for r in rows),
        "tokens_out": sum(r["tokens_out"] for r in rows),
        "cost_usd": round(sum(r["cost"] for r in rows), 6),
        "requests": sum(r["requests"] for r in rows),
    }

    return {
        "range": range_key,
        "days": days,
        "filters": {"provider": provider, "model": model, "key_id": key_id},
        "series": rows,
        "by_provider": _group_totals(rows, "provider"),
        "by_model": _group_totals(rows, "model"),
        "totals": totals,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _group_totals(rows: List[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        name = row.get(field) or "unknown"
        bucket = buckets.setdefault(
            name,
            {field: name, "requests": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0},
        )
        bucket["requests"] += row.get("requests") or 0
        bucket["tokens_in"] += row.get("tokens_in") or 0
        bucket["tokens_out"] += row.get("tokens_out") or 0
        bucket["cost_usd"] += row.get("cost") or 0.0

    for bucket in buckets.values():
        bucket["requests"] = int(bucket["requests"])
        bucket["tokens_in"] = int(bucket["tokens_in"])
        bucket["tokens_out"] = int(bucket["tokens_out"])
        bucket["cost_usd"] = round(float(bucket["cost_usd"]), 6)

    return sorted(buckets.values(), key=lambda b: b["cost_usd"], reverse=True)


async def query_logs(limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """Recent request rows, newest first, for the logs table."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    sql = text(
        """
        SELECT id, created_at, key_id, model, provider,
               tokens_in, tokens_out, cost, latency_ms,
               pii_redacted, injection_blocked, cache_hit, cache_similarity,
               gateway_mode, fallback_from, finish_reason
        FROM requests
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """
    )
    count_sql = text("SELECT count(*) AS total FROM requests")

    rows: List[Dict[str, Any]] = []
    total = 0

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(sql, {"limit": limit, "offset": offset})
            rows = [dict(row) for row in result.mappings().all()]
            total = (await session.execute(count_sql)).scalar() or 0
    except Exception as err:
        return {
            "rows": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "error": f"{type(err).__name__}: {err}",
        }

    for row in rows:
        if hasattr(row.get("created_at"), "isoformat"):
            row["created_at"] = row["created_at"].isoformat()
        if row.get("cost") is not None:
            row["cost"] = round(row["cost"], 6)

    return {
        "rows": rows,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < int(total),
    }


async def query_cache_stats() -> Dict[str, Any]:
    """Cache hit rate, avoided cost and similarity distribution."""
    sql = text(
        """
        SELECT
            count(*)                                            AS total,
            count(*) FILTER (WHERE cache_hit)                   AS hits,
            coalesce(avg(cache_similarity) FILTER (WHERE cache_hit), 0) AS avg_similarity,
            coalesce(sum(cost) FILTER (WHERE cache_hit), 0)     AS saved_cost_usd,
            coalesce(sum(cost), 0)                              AS total_cost_usd
        FROM requests
        WHERE created_at >= now() - interval '30 days'
        """
    )

    try:
        async with AsyncSessionLocal() as session:
            row = dict((await session.execute(sql)).mappings().first() or {})
    except Exception as err:
        return {
            "enabled": True,
            "error": f"{type(err).__name__}: {err}",
            "total_requests": 0,
            "hits": 0,
            "misses": 0,
            "hit_rate": 0.0,
            "avg_similarity": 0.0,
            "saved_cost_usd": 0.0,
            "total_cost_usd": 0.0,
            "window_days": 30,
        }

    total = int(row.get("total") or 0)
    hits = int(row.get("hits") or 0)
    saved = float(row.get("saved_cost_usd") or 0.0)

    return {
        "enabled": True,
        "total_requests": total,
        "hits": hits,
        "misses": total - hits,
        "hit_rate": round(hits / total, 4) if total else 0.0,
        "avg_similarity": round(float(row.get("avg_similarity") or 0.0), 4),
        "saved_cost_usd": round(saved, 6),
        "total_cost_usd": round(float(row.get("total_cost_usd") or 0.0), 6),
        "window_days": 30,
    }


def _empty_usage(range_key: str, days: int, error: str) -> Dict[str, Any]:
    return {
        "range": range_key,
        "days": days,
        "filters": {},
        "series": [],
        "by_provider": [],
        "by_model": [],
        "totals": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "requests": 0},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }


async def read_balances(max_age_seconds: int = 300) -> Dict[str, Any]:
    """Serve cached balances when fresh enough, otherwise fetch live.

    A cache holding no readable balance is worse than no cache: it would show
    "unknown" everywhere and mask a provider that has since come back. So the
    cache is only used when it has at least one available provider.
    """
    from lunair.services.balance_service import get_cached_balances

    cached = await get_cached_balances(max_age_seconds=max_age_seconds)
    if cached and cached.get("providers_available", 0) > 0:
        return cached
    return await collect_balances()