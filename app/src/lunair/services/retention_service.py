"""Retention and materialized-view maintenance."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import text

from lunair.config import settings
from lunair.db.base import AsyncSessionLocal

logger = logging.getLogger("lunair.retention")

DEFAULT_RETENTION_DAYS = 30
HARD_CAP_DAYS = 180


def effective_retention_days() -> int:
    """Configured retention, clamped to the documented hard cap."""
    configured = settings.get_yaml_config().get("security", {}).get(
        "log_retention_days", DEFAULT_RETENTION_DAYS
    )
    try:
        days = int(configured)
    except (TypeError, ValueError):
        days = DEFAULT_RETENTION_DAYS
    return max(1, min(days, HARD_CAP_DAYS))


async def refresh_daily_usage() -> Dict[str, Any]:
    """Rebuild the daily_usage materialized view.

    A plain REFRESH: the view is small (daily aggregates) and REFRESH
    CONCURRENTLY cannot run inside a transaction block.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("REFRESH MATERIALIZED VIEW daily_usage"))
            await session.commit()
        return {"refreshed": True}
    except Exception as err:
        logger.warning("daily_usage refresh failed: %s: %s", type(err).__name__, err)
        return {"refreshed": False, "error": f"{type(err).__name__}: {err}"}


async def list_request_partitions() -> List[Dict[str, Any]]:
    """Every partition of the partitioned requests table, with bounds."""
    sql = text(
        """
        SELECT c.relname                        AS name,
               pg_get_expr(c.relpartbound, c.oid) AS bounds
        FROM pg_class c
        JOIN pg_inherits i ON i.inhrelid = c.oid
        JOIN pg_class parent ON parent.oid = i.inhparent
        WHERE parent.relname = 'requests'
        ORDER BY c.relname
        """
    )

    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(sql)).mappings().all()
    except Exception as err:
        logger.warning("partition listing failed: %s: %s", type(err).__name__, err)
        return []

    return [dict(row) for row in rows]


def _partition_start(bounds: str) -> datetime | None:
    """Extract the FROM bound from a pg_get_expr partition bound string."""
    if not bounds or "FOR VALUES" not in bounds:
        return None

    payload = bounds.split("FROM")[-1]
    for token in payload.replace("(", " ").replace(")", " ").split():
        token = token.strip().strip("'")
        if len(token) == 10 and token.count("-") == 2:
            try:
                return datetime.strptime(token, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


async def drop_expired_partitions(retention_days: int | None = None) -> Dict[str, Any]:
    """Drop request-log partitions entirely older than the retention window.

    Dropping a partition is far cheaper than DELETE on the parent, and it
    reclaims disk immediately. The default partition is never dropped — it
    holds anything outside the explicit month ranges.
    """
    days = retention_days if retention_days is not None else effective_retention_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    dropped: List[str] = []
    skipped: List[Dict[str, Any]] = []

    for partition in await list_request_partitions():
        name = partition["name"]
        if name.endswith("_default"):
            skipped.append({"name": name, "reason": "default partition is retained"})
            continue

        start = _partition_start(partition.get("bounds") or "")
        if start is None:
            skipped.append({"name": name, "reason": "could not parse partition bound"})
            continue

        if start >= cutoff:
            continue

        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
                await session.commit()
            dropped.append(name)
            logger.info("dropped expired partition %s (started %s)", name, start.date())
        except Exception as err:
            skipped.append({"name": name, "reason": f"{type(err).__name__}: {err}"})

    return {
        "retention_days": days,
        "cutoff": cutoff.isoformat(),
        "dropped": dropped,
        "dropped_count": len(dropped),
        "skipped": skipped,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }