"""Per-provider circuit breaker.

Unlike the previous tracker this one actually *short-circuits*: ``is_available``
returns False while a provider is open, so the router skips known-bad providers
for the cooldown window instead of paying a failed round trip every request.
Thresholds come from ``config/config.yaml`` (``gateway.circuit_breaker``).
"""

import time
from typing import Any, Dict, Optional

from lunair.config import settings

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 60


def _failure_threshold() -> int:
    try:
        return int(settings.get_circuit_breaker_config().get("failure_threshold", DEFAULT_FAILURE_THRESHOLD))
    except (TypeError, ValueError):
        return DEFAULT_FAILURE_THRESHOLD


def _cooldown_seconds() -> int:
    try:
        return int(settings.get_circuit_breaker_config().get("cooldown_seconds", DEFAULT_COOLDOWN_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_COOLDOWN_SECONDS


class _Breaker:
    __slots__ = ("failures", "state", "opened_at", "last_failure_at", "total_failures")

    def __init__(self) -> None:
        self.failures = 0
        self.state = CLOSED
        self.opened_at = 0.0
        self.last_failure_at: Optional[float] = None
        self.total_failures = 0


_breakers: Dict[str, _Breaker] = {}


def record_success(provider: str) -> None:
    breaker = _breakers.setdefault(provider, _Breaker())
    breaker.failures = 0
    breaker.state = CLOSED
    breaker.opened_at = 0.0


def record_failure(
    provider: str,
    threshold: Optional[int] = None,
    cooldown_seconds: Optional[int] = None,
) -> None:
    limit = threshold if threshold is not None else _failure_threshold()
    breaker = _breakers.setdefault(provider, _Breaker())
    breaker.failures += 1
    breaker.total_failures += 1
    breaker.last_failure_at = time.time()
    if breaker.failures >= limit:
        breaker.state = OPEN
        breaker.opened_at = time.time()


def is_available(provider: str, cooldown_seconds: Optional[int] = None) -> bool:
    """Whether a request may be attempted against this provider.

    An OPEN breaker whose cooldown has elapsed transitions to HALF_OPEN and
    admits a single probe request.
    """
    breaker = _breakers.get(provider)
    if breaker is None or breaker.state == CLOSED:
        return True
    if breaker.state == HALF_OPEN:
        return True

    cooldown = cooldown_seconds if cooldown_seconds is not None else _cooldown_seconds()
    if time.time() - breaker.opened_at >= cooldown:
        breaker.state = HALF_OPEN
        return True
    return False


def get_state(provider: str, cooldown_seconds: Optional[int] = None) -> Dict[str, Any]:
    breaker = _breakers.get(provider)
    if breaker is None:
        return {
            "provider": provider,
            "state": CLOSED,
            "consecutive_failures": 0,
            "total_failures": 0,
            "last_failure_at": None,
            "retry_in_s": 0,
        }

    cooldown = cooldown_seconds if cooldown_seconds is not None else _cooldown_seconds()
    state = breaker.state
    retry_in = 0.0

    if state == OPEN and breaker.opened_at:
        elapsed = time.time() - breaker.opened_at
        if elapsed >= cooldown:
            state = HALF_OPEN
            breaker.state = HALF_OPEN
        else:
            retry_in = cooldown - elapsed

    last_failure = None
    if breaker.last_failure_at:
        last_failure = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(breaker.last_failure_at)
        )

    return {
        "provider": provider,
        "state": state,
        "consecutive_failures": breaker.failures,
        "total_failures": breaker.total_failures,
        "last_failure_at": last_failure,
        "retry_in_s": round(retry_in, 1),
    }


def get_circuit_states() -> Dict[str, Dict[str, Any]]:
    """State for every configured provider, including those never called."""
    states = {name: get_state(name) for name in settings.get_provider_status()}
    states.update({name: get_state(name) for name in _breakers})
    return states


def reset() -> None:
    _breakers.clear()
