from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select

from lunair.config import settings
from lunair.db.base import AsyncSessionLocal
from lunair.db.models import BalanceSnapshot


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _provider_config() -> List[Dict[str, Any]]:
    return settings.get_yaml_config().get("balance", {}).get("providers", []) or []


async def fetch_provider_balance(
    client: httpx.AsyncClient, provider: str, endpoint: str
) -> Dict[str, Any]:
    """Call one provider balance endpoint and normalize to USD.

    Providers disagree on shape and units, so each is mapped explicitly.
    An unreachable or unexpected endpoint yields ``available: false`` rather
    than raising — a balance view is not worth failing a request over.
    """
    result: Dict[str, Any] = {
        "provider": provider,
        "balance_usd": None,
        "lifetime_spend_usd": None,
        "available": False,
        "note": None,
    }

    try:
        response = await client.get(endpoint, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as err:
        result["note"] = f"HTTP {err.response.status_code}"
        return result
    except Exception as err:
        result["note"] = f"unreachable: {type(err).__name__}"
        return result

    try:
        if provider == "openai":
            # /dashboard/billing/credit_grants — undocumented, normal API keys only.
            # total_available is authoritative; the subtraction is a fallback for
            # accounts where the field is absent.
            available = _to_float(payload.get("total_available"))
            if available is None:
                granted = _to_float(payload.get("total_granted"))
                used = _to_float(payload.get("total_used"))
                if granted is None or used is None:
                    result["note"] = "no total_available in response"
                    return result
                available = granted - used
            result["balance_usd"] = available
            result["lifetime_spend_usd"] = _to_float(payload.get("total_used"))
        elif provider == "openrouter":
            # /v1/credits — requires a management key, not a regular API key.
            data = payload.get("data") or {}
            credits = _to_float(data.get("total_credits"))
            usage = _to_float(data.get("total_usage"))
            if credits is None:
                result["note"] = "no total_credits in response"
                return result
            result["balance_usd"] = credits - (usage or 0.0)
            result["lifetime_spend_usd"] = usage
        elif provider == "deepseek":
            # /user/balance -> {"balance_infos": [{"currency": "USD", "total_balance": "..."}]}
            infos = payload.get("balance_infos") or []
            for info in infos:
                if str(info.get("currency", "")).upper() == "USD":
                    result["balance_usd"] = _to_float(info.get("total_balance"))
                    break
            else:
                result["note"] = "no USD balance in response"
                return result
        elif provider == "groq":
            # Usage-based billing with no prepaid balance endpoint.
            result["note"] = "usage-based, no prepaid balance"
            return result
        else:
            result["note"] = f"unmapped provider: {provider}"
            return result
    except Exception as err:
        result["note"] = f"unexpected response shape: {type(err).__name__}"
        return result

    result["available"] = result["balance_usd"] is not None
    if result["available"]:
        result["last_refreshed"] = _now().isoformat()
    return result


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def collect_balances() -> Dict[str, Any]:
    """Aggregate balances across every provider in config."""
    providers = _provider_config()
    async with httpx.AsyncClient() as client:
        results = await _gather_all(client, providers)

    by_provider = {item["provider"]: item for item in results}

    known = [item["balance_usd"] for item in results if item["balance_usd"] is not None]
    total = sum(known) if known else None

    return {
        "providers": [by_provider[p["name"]] for p in providers if p["name"] in by_provider],
        "total_remaining_usd": total,
        "providers_available": len(known),
        "providers_total": len(providers),
        "last_refreshed": _now().isoformat(),
    }


async def _gather_all(
    client: httpx.AsyncClient, providers: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    import asyncio

    tasks = [
        fetch_provider_balance(client, p.get("name", "unknown"), p.get("endpoint", ""))
        for p in providers
    ]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for provider, outcome in zip(providers, gathered):
        if isinstance(outcome, BaseException):
            results.append(
                {
                    "provider": provider.get("name", "unknown"),
                    "balance_usd": None,
                    "lifetime_spend_usd": None,
                    "available": False,
                    "note": f"error: {type(outcome).__name__}",
                }
            )
        else:
            results.append(outcome)
    return results


async def refresh_balances() -> Dict[str, Any]:
    """Fetch balances and persist one row per provider."""
    summary = await collect_balances()

    try:
        async with AsyncSessionLocal() as session:
            for item in summary["providers"]:
                session.add(
                    BalanceSnapshot(
                        provider=item["provider"],
                        balance_usd=item["balance_usd"],
                        lifetime_spend_usd=item["lifetime_spend_usd"],
                    )
                )
            await session.commit()
    except Exception:
        # Snapshot persistence is best-effort; the live response still stands.
        pass

    return summary


async def get_cached_balances(max_age_seconds: int = 300) -> Optional[Dict[str, Any]]:
    """Return the most recent snapshot set, if recent enough to be useful."""
    cutoff = _now().timestamp() - max_age_seconds

    try:
        async with AsyncSessionLocal() as session:
            stmt = select(BalanceSnapshot).order_by(BalanceSnapshot.snapshot_at.desc())
            rows = (await session.execute(stmt)).scalars().all()
    except Exception:
        return None

    if not rows:
        return None

    newest = rows[0].snapshot_at
    if newest is None or newest.timestamp() < cutoff:
        return None

    latest: Dict[str, BalanceSnapshot] = {}
    for row in rows:
        latest.setdefault(row.provider, row)

    providers = []
    for name, row in latest.items():
        available = row.balance_usd is not None
        providers.append(
            {
                "provider": name,
                "balance_usd": row.balance_usd,
                "lifetime_spend_usd": row.lifetime_spend_usd,
                "available": available,
                "note": None if available else "no balance reported at last refresh",
                "last_refreshed": row.snapshot_at.isoformat() if row.snapshot_at else None,
            }
        )

    known = [p["balance_usd"] for p in providers if p["balance_usd"] is not None]
    return {
        "providers": providers,
        "total_remaining_usd": sum(known) if known else None,
        "providers_available": len(known),
        "providers_total": len(providers),
        "last_refreshed": newest.isoformat() if newest else None,
    }