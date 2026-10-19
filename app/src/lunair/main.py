import asyncio
import logging
from asyncio import sleep
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from lunair.api.middleware import RequestIDMiddleware
from lunair.api.routes.chat import router_api as chat_router
from lunair.api.routes.internal import internal_api
from lunair.api.routes.keys import keys_api
from lunair.api.routes.models import models_api as models_router
from lunair.api.routes.usage import usage_api
from lunair.config import settings
from lunair.db.base import AsyncSessionLocal, engine
from lunair.db.redis import redis_available
from lunair.reliability.circuit_breaker import get_circuit_states
from lunair.schemas.chat import ChatCompletionRequest
from lunair.schemas.common import HealthResponse
from lunair.services.balance_service import refresh_balances
from lunair.services.retention_service import (
    default_partition_row_count,
    drop_expired_partitions,
    ensure_future_partitions,
    refresh_daily_usage,
)

logger = logging.getLogger("lunair")
logging.basicConfig(level=logging.INFO)

MATVIEW_REFRESH_SECONDS = 3600
RETENTION_HOUR_UTC = 3

# Arbitrary constant identifying the background-jobs advisory lock.
LEADER_LOCK_KEY = 727_101_001


async def _acquire_leader():
    """Try to become the single replica that owns background jobs.

    Uses a session-level Postgres advisory lock on a dedicated connection held
    for the process lifetime. Returns the connection if acquired, else None.
    """
    try:
        conn = await engine.connect()
        acquired = (
            await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LEADER_LOCK_KEY})
        ).scalar()
        if acquired:
            return conn
        await conn.close()
        return None
    except Exception as err:
        logger.warning("leader election unavailable: %s", type(err).__name__)
        return None


async def _dependency_status() -> dict:
    db_ok = False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False
    return {"database": db_ok, "redis": await redis_available()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own the periodic background jobs for the process lifetime."""
    leader_conn = await _acquire_leader()
    app.state.leader_conn = leader_conn
    app.state.is_leader = leader_conn is not None

    if app.state.is_leader:
        try:
            created = await ensure_future_partitions()
            if created["created"]:
                logger.info("provisioned partitions: %s", ", ".join(created["created"]))
            default_rows = await default_partition_row_count()
            if default_rows:
                logger.warning(
                    "requests_default holds %s rows — partitions may have run out", default_rows
                )
        except Exception as err:
            logger.warning("partition provisioning failed: %s", type(err).__name__)

        app.state.background_tasks = [
            asyncio.create_task(_balance_refresh_loop()),
            asyncio.create_task(_matview_refresh_loop()),
            asyncio.create_task(_retention_loop()),
        ]
        logger.info("background jobs started (balance, matview, retention)")
    else:
        app.state.background_tasks = []
        logger.info("not the leader replica; background jobs delegated elsewhere")

    try:
        yield
    finally:
        for task in app.state.background_tasks:
            task.cancel()
        await asyncio.gather(*app.state.background_tasks, return_exceptions=True)
        app.state.background_tasks = []
        if app.state.leader_conn is not None:
            try:
                await app.state.leader_conn.close()
            except Exception:
                pass
        logger.info("background jobs stopped")


app = FastAPI(
    title="LunAIR",
    version=settings.version,
    description="LLM Unified Native AI Inference Router",
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

cors_origins = [
    origin.strip()
    for origin in (settings.cors_origins or "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins or ["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(models_router)
app.include_router(usage_api)
app.include_router(keys_api)
app.include_router(internal_api)


async def _balance_refresh_loop() -> None:
    """Refresh provider balances into balance_snapshots on an interval."""
    interval = _balance_refresh_seconds()
    while True:
        try:
            await sleep(interval)
            summary = await refresh_balances()
            logger.info(
                "balance refresh complete: %s/%s providers reachable",
                summary.get("providers_available", 0),
                summary.get("providers_total", 0),
            )
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.warning("balance refresh failed: %s", type(err).__name__)


async def _matview_refresh_loop() -> None:
    """Refresh daily_usage so dashboards never read stale aggregates."""
    while True:
        try:
            await sleep(MATVIEW_REFRESH_SECONDS)
            await refresh_daily_usage(concurrent=True)
            logger.info("daily_usage materialized view refreshed")
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.warning("matview refresh failed: %s", type(err).__name__)


async def _retention_loop() -> None:
    """Daily retention sweep, nominally at 03:00 UTC."""
    while True:
        await sleep(_seconds_until_retention_window())
        try:
            await ensure_future_partitions()
            result = await drop_expired_partitions()
            if result["dropped_count"]:
                logger.info(
                    "retention: dropped %s partition(s) older than %s days: %s",
                    result["dropped_count"],
                    result["retention_days"],
                    ", ".join(result["dropped"]),
                )
            else:
                logger.info("retention: nothing to drop (%s days)", result["retention_days"])
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.warning("retention sweep failed: %s", type(err).__name__)

        await sleep(23 * 3600)


def _seconds_until_retention_window() -> int:
    """Seconds from now until the next RETENTION_HOUR_UTC boundary."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=RETENTION_HOUR_UTC, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(60, int((target - now).total_seconds()))


def _balance_refresh_seconds() -> int:
    configured = settings.get_yaml_config().get("balance", {}).get(
        "refresh_interval_seconds", 300
    )
    try:
        return max(30, int(configured))
    except (TypeError, ValueError):
        return 300


@app.get("/health", response_model=HealthResponse)
async def health():
    provider_status = settings.get_provider_status()
    unconfigured = settings.get_unconfigured_providers()
    return HealthResponse(
        status="ok",
        version=settings.version,
        gateway_mode=settings.gateway_mode,
        details={
            "fastapi_url": settings.fastapi_url,
            "providers": provider_status,
            "unconfigured_providers": unconfigured,
            "providers_ready": len(provider_status) - len(unconfigured),
            "providers_total": len(provider_status),
            "circuit_breakers": get_circuit_states(),
            "dependencies": await _dependency_status(),
            "leader": getattr(app.state, "is_leader", False),
        },
    )


@app.get("/ready")
async def ready():
    """Readiness: 503 until Postgres and Redis are both reachable."""
    dependencies = await _dependency_status()
    ok = all(dependencies.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"ready": ok, "dependencies": dependencies},
    )


@app.post("/v1/echo")
async def echo_request(req: ChatCompletionRequest):
    return req.model_dump()
