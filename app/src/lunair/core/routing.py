"""Two-layer routing engine.

Given a requested model and a set of provider preferences, produce an **ordered
list of endpoints** to try. This is the policy layer that sits on top of the
endpoint registry:

1. resolve the model to its candidate endpoints (expanding ``auto/*`` aliases),
2. apply provider preferences (only / ignore / zdr / order / sort / max_price),
3. drop endpoints whose provider breaker is open,
4. order the survivors by the selected **strategy**.
"""

import random
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from lunair.core.registry import Endpoint, ModelRegistry
from lunair.reliability import circuit_breaker, stats

# Strategy identifiers (kept stable — they appear in config and the API).
PRIORITY = "priority"
WEIGHTED = "weighted"
ROUND_ROBIN = "round_robin"
RANDOM = "random"
LEAST_USED = "least_used"
P2C = "p2c"
COST_OPTIMIZED = "cost_optimized"
LATENCY_OPTIMIZED = "latency_optimized"
THROUGHPUT_OPTIMIZED = "throughput_optimized"
LKGP = "lkgp"
CACHE_OPTIMIZED = "cache_optimized"
AUTO = "auto"

STRATEGIES = {
    PRIORITY, WEIGHTED, ROUND_ROBIN, RANDOM, LEAST_USED, P2C,
    COST_OPTIMIZED, LATENCY_OPTIMIZED, THROUGHPUT_OPTIMIZED, LKGP,
    CACHE_OPTIMIZED, AUTO,
}

DEFAULT_AUTO_WEIGHTS = {"cost": 0.35, "latency": 0.30, "success": 0.25, "load": 0.10}

_rr_lock = threading.Lock()
_rr_counters: Dict[str, int] = {}
_cache_pins: Dict[str, str] = {}


@dataclass
class ProviderPreferences:
    order: Optional[List[str]] = None
    only: Optional[List[str]] = None
    ignore: Optional[List[str]] = None
    sort: Optional[str] = None            # price | throughput | latency
    max_price: Optional[float] = None     # USD per 1M tokens
    zdr: bool = False
    data_collection: Optional[str] = None  # allow | deny
    allow_fallbacks: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_request(cls, provider_obj: Optional[Dict[str, Any]]) -> "ProviderPreferences":
        obj = provider_obj or {}
        return cls(
            order=_as_list(obj.get("order")),
            only=_as_list(obj.get("only")),
            ignore=_as_list(obj.get("ignore")),
            sort=obj.get("sort") if isinstance(obj.get("sort"), str) else None,
            max_price=_as_float(obj.get("max_price")),
            zdr=bool(obj.get("zdr", False)),
            data_collection=obj.get("data_collection"),
            allow_fallbacks=bool(obj.get("allow_fallbacks", True)),
            extra=obj,
        )


def _as_list(value: Any) -> Optional[List[str]]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return None


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --- alias expansion --------------------------------------------------------

def resolve_alias(model: str, routing_cfg: Dict[str, Any]) -> Tuple[List[str], Optional[str], bool]:
    """Expand ``auto/*`` aliases into ``(candidate_models, strategy, is_alias)``."""
    aliases = routing_cfg.get("aliases") or {}
    spec = aliases.get(model)
    if spec is None:
        # Backward-compatible shape: routing: {auto/cheap: [models...]}
        spec = routing_cfg.get(model)
    if spec is None:
        return [model], None, False
    if isinstance(spec, list):
        return (list(spec), None, True) if spec else ([model], None, False)
    if isinstance(spec, dict):
        candidates = spec.get("candidates") or []
        if not candidates:
            return [model], None, False
        return list(candidates), spec.get("strategy"), True
    return [model], None, False


def default_strategy(routing_cfg: Dict[str, Any]) -> str:
    strategy = routing_cfg.get("strategy") or PRIORITY
    return strategy if strategy in STRATEGIES else PRIORITY


# --- preference filtering ---------------------------------------------------

def apply_preferences(
    endpoints: List[Endpoint], prefs: ProviderPreferences
) -> Tuple[List[Endpoint], Optional[str]]:
    """Filter endpoints by provider preferences. Returns (endpoints, error)."""
    result = list(endpoints)

    if prefs.only:
        allowed = set(prefs.only)
        result = [e for e in result if e.provider in allowed]
    if prefs.ignore:
        blocked = set(prefs.ignore)
        result = [e for e in result if e.provider not in blocked]
    if prefs.zdr or prefs.data_collection == "deny":
        zdr = [e for e in result if e.zdr]
        if zdr:
            result = zdr
        else:
            return [], "no zero-data-retention endpoint available for this model"
    if prefs.max_price is not None:
        affordable = [e for e in result if e.blended_price and e.blended_price <= prefs.max_price]
        if not affordable:
            return [], f"no endpoint at or below max_price ${prefs.max_price}/1M tokens"
        result = affordable

    return result, None


# --- strategy ordering ------------------------------------------------------

def _snap(name: str) -> Dict[str, Any]:
    return stats.snapshot(name)


def _cost_key(ep: Endpoint) -> float:
    return ep.blended_price if ep.blended_price else float("inf")


def _latency_key(ep: Endpoint) -> float:
    p95 = _snap(ep.deployment_name).get("p95_ms")
    return p95 if p95 is not None else float("inf")


def order_endpoints(
    endpoints: List[Endpoint],
    strategy: str,
    *,
    model_id: str = "",
    prompt_hash: Optional[str] = None,
    auto_weights: Optional[Dict[str, float]] = None,
) -> List[Endpoint]:
    if len(endpoints) <= 1 or strategy == PRIORITY:
        return list(endpoints)

    if strategy == WEIGHTED:
        return sorted(endpoints, key=lambda e: random.random() ** (1.0 / max(e.weight, 0.001)), reverse=True)

    if strategy == RANDOM:
        shuffled = list(endpoints)
        random.shuffle(shuffled)
        return shuffled

    if strategy == ROUND_ROBIN:
        with _rr_lock:
            start = _rr_counters.get(model_id, 0) % len(endpoints)
            _rr_counters[model_id] = start + 1
        return endpoints[start:] + endpoints[:start]

    if strategy == LEAST_USED:
        return sorted(endpoints, key=lambda e: (_snap(e.deployment_name).get("inflight", 0), e.deployment_name))

    if strategy == P2C:
        if len(endpoints) < 2:
            return list(endpoints)
        a, b = random.sample(endpoints, 2)
        first, second = (a, b) if _snap(a.deployment_name).get("inflight", 0) <= _snap(b.deployment_name).get("inflight", 0) else (b, a)
        rest = [e for e in endpoints if e not in (first, second)]
        return [first, second] + rest

    if strategy == COST_OPTIMIZED:
        return sorted(endpoints, key=_cost_key)

    if strategy in (LATENCY_OPTIMIZED, THROUGHPUT_OPTIMIZED):
        return sorted(endpoints, key=_latency_key)

    if strategy == LKGP:
        return sorted(
            endpoints,
            key=lambda e: _snap(e.deployment_name).get("last_success_ts") or 0.0,
            reverse=True,
        )

    if strategy == CACHE_OPTIMIZED and prompt_hash:
        pinned = _cache_pins.get(f"{model_id}:{prompt_hash}")
        if pinned:
            pinned_eps = [e for e in endpoints if e.deployment_name == pinned]
            if pinned_eps:
                return pinned_eps + [e for e in endpoints if e.deployment_name != pinned]

    if strategy == AUTO:
        weights = {**DEFAULT_AUTO_WEIGHTS, **(auto_weights or {})}
        return sorted(endpoints, key=lambda e: _auto_score(e, weights))

    return list(endpoints)


def _auto_score(ep: Endpoint, weights: Dict[str, float]) -> float:
    """Lower is better. Blends cost, latency, success rate and current load."""
    snap = _snap(ep.deployment_name)

    cost = ep.blended_price or 0.0
    latency = snap.get("p95_ms") or 0.0
    success = snap.get("success_rate")
    success = 1.0 if success is None else success
    load = snap.get("inflight", 0)

    # Normalise to comparable 0..1-ish scales.
    cost_norm = min(cost / 50.0, 1.0)          # 50 USD/1M as the ceiling
    latency_norm = min(latency / 5000.0, 1.0)  # 5s p95 as the ceiling
    load_norm = min(load / 10.0, 1.0)

    return (
        weights["cost"] * cost_norm
        + weights["latency"] * latency_norm
        + weights["success"] * (1.0 - success)
        + weights["load"] * load_norm
    )


def pin_cache_endpoint(model_id: str, prompt_hash: str, deployment_name: str) -> None:
    _cache_pins[f"{model_id}:{prompt_hash}"] = deployment_name


# --- top-level selection ----------------------------------------------------

def select_endpoints(
    model: str,
    *,
    registry: ModelRegistry,
    routing_cfg: Dict[str, Any],
    prefs: ProviderPreferences,
    prompt_hash: Optional[str] = None,
    available_providers: Optional[set] = None,
) -> Tuple[List[Endpoint], str, Optional[str]]:
    """Return ``(ordered_endpoints, strategy, error)`` for a request."""
    candidate_models, alias_strategy, is_alias = resolve_alias(model, routing_cfg)
    strategy = alias_strategy or default_strategy(routing_cfg)

    endpoints: List[Endpoint] = []
    for model_id in candidate_models:
        endpoints.extend(registry.endpoints_for(model_id))

    if not endpoints:
        return [], strategy, f"unknown model '{model}'"

    endpoints, error = apply_preferences(endpoints, prefs)
    if error:
        return [], strategy, error

    if available_providers is not None:
        usable = [e for e in endpoints if e.provider in available_providers]
        if usable:
            endpoints = usable

    # Drop endpoints whose provider breaker is open (probe if all are open).
    healthy = [e for e in endpoints if circuit_breaker.is_available(e.provider)]
    if healthy:
        endpoints = healthy

    ordered = order_endpoints(
        endpoints,
        strategy,
        model_id=model,
        prompt_hash=prompt_hash,
        auto_weights=routing_cfg.get("auto_weights"),
    )
    return ordered, strategy, None


def reset() -> None:
    """Clear routing counters/pins (used by tests)."""
    with _rr_lock:
        _rr_counters.clear()
    _cache_pins.clear()
