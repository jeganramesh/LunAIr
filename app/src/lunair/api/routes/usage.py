from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from lunair.services.usage_service import (
    RANGE_TO_DAYS,
    query_cache_stats,
    query_logs,
    query_usage,
    read_balances,
)

usage_api = APIRouter(prefix="/v1", tags=["usage"])


class ProviderBalance(BaseModel):
    provider: str
    balance_usd: Optional[float] = None
    lifetime_spend_usd: Optional[float] = None
    available: bool = False
    note: Optional[str] = None
    last_refreshed: Optional[str] = None


class BalanceResponse(BaseModel):
    providers: List[ProviderBalance]
    total_remaining_usd: Optional[float] = None
    providers_available: int = 0
    providers_total: int = 0
    last_refreshed: Optional[str] = None


@usage_api.get("/balance", response_model=BalanceResponse)
async def get_balance(max_age: int = Query(300, ge=0, le=3600)) -> Dict[str, Any]:
    """Unified provider balance in USD, served from cache when fresh."""
    return await read_balances(max_age_seconds=max_age)


@usage_api.get("/usage")
async def get_usage(
    range: str = Query("7d"),
    provider: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    key_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Time-series usage from the daily_usage materialized view."""
    if range not in RANGE_TO_DAYS:
        return {
            "range": range,
            "days": 0,
            "filters": {},
            "series": [],
            "by_provider": [],
            "by_model": [],
            "totals": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "requests": 0},
            "error": f"unsupported range '{range}'; expected one of {sorted(RANGE_TO_DAYS)}",
        }
    return await query_usage(range_key=range, provider=provider, model=model, key_id=key_id)


@usage_api.get("/usage/logs")
async def get_logs(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Paginated request log rows, newest first."""
    return await query_logs(limit=limit, offset=offset)


@usage_api.get("/usage/cache")
async def get_cache_stats() -> Dict[str, Any]:
    """Cache hit rate, avoided spend and similarity average."""
    return await query_cache_stats()


@usage_api.get("/benchmark")
async def get_benchmark() -> Dict[str, Any]:
    """Serve the most recent scripts/bench.sh output, if present."""
    from pathlib import Path
    import json

    candidates = [
        Path("scripts/bench-results.json"),
        Path("../scripts/bench-results.json"),
        Path("/app/scripts/bench-results.json"),
    ]

    for candidate in candidates:
        if candidate.is_file():
            try:
                with open(candidate, "r", encoding="utf-8") as handle:
                    return {"available": True, **json.load(handle)}
            except Exception as err:
                return {
                    "available": False,
                    "error": f"failed to read {candidate}: {type(err).__name__}",
                    "hint": "run scripts/bench.sh to generate results",
                }

    return {
        "available": False,
        "hint": "run scripts/bench.sh to generate results",
        "results": [],
    }