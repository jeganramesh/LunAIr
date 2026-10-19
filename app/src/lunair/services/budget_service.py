"""Per-key monthly budget enforcement.

Spend is summed from the partitioned ``requests`` table for the current UTC
month and compared against the key's ``monthly_budget_usd`` (falling back to
``budgets.default_monthly_usd`` from config). Thresholds come from
``budgets.warn_at_pct`` / ``budgets.block_at_pct``.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text

from lunair.config import settings
from lunair.db.base import AsyncSessionLocal
from lunair.db.models import APIKey

WARN = "warn"
BLOCK = "block"
OK = "ok"


@dataclass
class BudgetStatus:
    allowed: bool
    spend_usd: float = 0.0
    limit_usd: float = 0.0
    pct: float = 0.0
    action: str = OK
    reason: Optional[str] = None


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def current_month_spend(key_id: str) -> float:
    sql = text(
        """
        SELECT coalesce(sum(cost), 0) AS spend
        FROM requests
        WHERE key_id = :key_id AND created_at >= :since
        """
    )
    try:
        async with AsyncSessionLocal() as session:
            value = (await session.execute(sql, {"key_id": key_id, "since": _month_start()})).scalar()
            return float(value or 0.0)
    except Exception:
        return 0.0


async def limit_for_key(key_id: str) -> Optional[float]:
    """Per-key monthly budget, or None when the key has no row (e.g. gateway)."""
    try:
        async with AsyncSessionLocal() as session:
            value = (
                await session.execute(
                    select(APIKey.monthly_budget_usd).where(APIKey.id == key_id)
                )
            ).scalar_one_or_none()
            return float(value) if value is not None else None
    except Exception:
        return None


async def check_budget(key_id: str, monthly_limit: Optional[float]) -> BudgetStatus:
    cfg = settings.get_budget_config()
    limit = float(monthly_limit or cfg.get("default_monthly_usd", 50) or 50)
    warn_pct = float(cfg.get("warn_at_pct", 80) or 80)
    block_pct = float(cfg.get("block_at_pct", 100) or 100)

    if not settings.budget_enforcement or limit <= 0:
        return BudgetStatus(allowed=True, limit_usd=limit)

    spend = await current_month_spend(key_id)
    pct = (spend / limit * 100.0) if limit else 0.0

    if pct >= block_pct:
        return BudgetStatus(
            allowed=False, spend_usd=spend, limit_usd=limit, pct=pct,
            action=BLOCK, reason="monthly budget exceeded",
        )

    action = WARN if pct >= warn_pct else OK
    return BudgetStatus(allowed=True, spend_usd=spend, limit_usd=limit, pct=pct, action=action)
