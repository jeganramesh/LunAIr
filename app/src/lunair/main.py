import asyncio
import logging
from asyncio import sleep
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from lunair.api.routes.chat import router_api as chat_router
from lunair.api.routes.models import models_api as models_router
from lunair.api.routes.usage import usage_api
from lunair.config import settings
from lunair.reliability.circuit_breaker import get_circuit_states
from lunair.schemas.chat import ChatCompletionRequest
from lunair.schemas.common import HealthResponse
from lunair.services.balance_service import refresh_balances
from lunair.services.retention_service import drop_expired_partitions, refresh_daily_usage

logger = logging.getLogger("lunair")
logging.basicConfig(level=logging.INFO)

MATVIEW_REFRESH_SECONDS = 3600
RETENTION_HOUR_UTC = 3


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own the periodic background jobs for the process lifetime."""
    app.state.background_tasks = [
        asyncio.create_task(_balance_refresh_loop()),
        asyncio.create_task(_matview_refresh_loop()),
        asyncio.create_task(_retention_loop()),
    ]
    logger.info("background jobs started (balance, matview, retention)")

    try:
        yield
    finally:
        for task in app.state.background_tasks:
            task.cancel()
        # Let cancellations unwind so the loops can observe them.
        await asyncio.gather(*app.state.background_tasks, return_exceptions=True)
        app.state.background_tasks = []
        logger.info("background jobs stopped")


app = FastAPI(
    title="LunAIR",
    version=settings.version,
    description="LLM Unified Native AI Inference Router",
    lifespan=lifespan,
)

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


async def _balance_refresh_loop() -> None:
    """Refresh provider balances into balance_snapshots on an interval."""
    interval = _balance_refresh_seconds()
    while True:
        try:
            await sleep(interval)
            summary = await refresh_balances()
            available = summary.get("providers_available", 0)
            logger.info(
                "balance refresh complete: %s/%s providers reachable",
                available,
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
            await refresh_daily_usage()
            logger.info("daily_usage materialized view refreshed")
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.warning("matview refresh failed: %s", type(err).__name__)


async def _retention_loop() -> None:
    """Daily retention sweep, nominally at 03:00 UTC.

    Sleeping until the next scheduled hour instead of a fixed 24h interval, so
    the sweep does not drift and does not fire on every replica at once.
    """
    while True:
        await sleep(_seconds_until_retention_window())
        try:
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

        # Never run twice in the same day.
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
        },
    )


@app.post("/v1/echo")
async def echo_request(req: ChatCompletionRequest):
    return req.model_dump()
