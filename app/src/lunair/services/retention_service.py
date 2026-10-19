"""Retention, partition provisioning and materialized-view maintenance."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from lunair.config import settings
from lunair.db.base import AsyncSessionLocal, engine

logger = logging.getLogger("lunair.retention")

DEFAULT_RETENTION_DAYS = 30
HARD_CAP_DAYS = 180


def effective_retention_days() -> int:
    """Configured retention, clamped to the documented hard cap."""
    configured = settings.get_security_config().get("log_retention_days", DEFAULT_RETENTION_DAYS)
    try:
        days = int(configured)
    except (TypeError, ValueError):
        days = DEFAULT_RETENTION_DAYS
    return max(1, min(days, HARD_CAP_DAYS))


def _add_months(moment: datetime, months: int) -> datetime:
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    return moment.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


def _partition_name(moment: datetime) -> str:
    return f"requests_y{moment.year}m{moment.month:02d}"


async def _partition_exists(name: str) -> bool:
    sql = text("SELECT to_regclass(:name) IS NOT NULL AS present")
    try:
        async with AsyncSessionLocal() as session:
            return bool((await session.execute(sql, {"name": name})).scalar())
    except Exception:
        return False


async def ensure_future_partitions(months_ahead: Optional[int] = None) -> Dict[str, Any]:
    """Create monthly ``requests`` partitions for the current and next months.

    Without this the partitioned table silently stops partitioning: every row
    past the last provisioned month lands in ``requests_default``, which
    retention never drops, so the table grows without bound.
    """
    ahead = months_ahead if months_ahead is not None else settings.partition_months_ahead
    now = datetime.now(timezone.utc)
    created: List[str] = []
    present: List[str] = []

    for offset in range(0, max(0, ahead) + 1):
        start = _add_months(now, offset)
        end = _add_months(now, offset + 1)
        name = _partition_name(start)

        if await _partition_exists(name):
            present.append(name)
            continue

        ddl = (
            f'CREATE TABLE IF NOT EXISTS "{name}" PARTITION OF requests '
            f"FOR VALUES FROM ('{start:%Y-%m-%d} 00:00:00+00') "
            f"TO ('{end:%Y-%m-%d} 00:00:00+00')"
        )
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text(ddl))
                await session.commit()
            created.append(name)
            logger.info("created request partition %s", name)
        except Exception as err:
            logger.warning("failed to create partition %s: %s", name, type(err).__name__)

    return {"created": created, "present": present}


async def default_partition_row_count() -> int:
    """Rows sitting in the catch-all partition — a signal partitions ran out."""
    try:
        async with AsyncSessionLocal() as session:
            value = (await session.execute(text("SELECT count(*) FROM requests_default"))).scalar()
            return int(value or 0)
    except Exception:
        return 0


async def refresh_daily_usage(concurrent: bool = True) -> Dict[str, Any]:
    """Rebuild the daily_usage materialized view.

    Prefers a CONCURRENT refresh (non-blocking for readers). That requires a
    unique index, which exists (``ux_daily_usage_key``), and must run outside a
    transaction — hence the AUTOCOMMIT connection. Falls back to a plain
    refresh if the concurrent path is unavailable.
    """
    if concurrent:
        try:
            async with engine.connect() as conn:
                conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY daily_usage"))
            return {"refreshed": True, "concurrent": True}
        except Exception as err:
            logger.warning("concurrent matview refresh failed (%s); retrying plain", type(err).__name__)

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("REFRESH MATERIALIZED VIEW daily_usage"))
            await session.commit()
        return {"refreshed": True, "concurrent": False}
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
