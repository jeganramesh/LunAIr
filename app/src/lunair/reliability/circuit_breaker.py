"""Per-provider circuit breaker state.

Phase 3 exposes read-only state for the dashboard. LiteLLM performs its own
internal cooldown handling, so this tracker records outcomes observed at the
edge without short-circuiting requests itself — a request is still attempted so
the provider gets a chance to recover.
"""

import time
from typing import Any, Dict

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 60


class _Breaker:
    __slots__ = ("failures", "state", "opened_at", "last_failure_at", "total_failures")

    def __init__(self) -> None:
        self.failures = 0
        self.state = CLOSED
        self.opened_at = 0.0
        self.last_failure_at: float | None = None
        self.total_failures = 0


_breakers: Dict[str, _Breaker] = {}


def record_success(provider: str) -> None:
    breaker = _breakers.setdefault(provider, _Breaker())
    breaker.failures = 0
    breaker.state = CLOSED
    breaker.opened_at = 0.0


def record_failure(provider: str, threshold: int = DEFAULT_FAILURE_THRESHOLD,
                   cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS) -> None:
    breaker = _breakers.setdefault(provider, _Breaker())
    breaker.failures += 1
    breaker.total_failures += 1
    breaker.last_failure_at = time.time()
    if breaker.failures >= threshold:
        breaker.state = OPEN
        breaker.opened_at = time.time()


def get_state(provider: str, cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS) -> Dict[str, Any]:
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

    state = breaker.state
    retry_in = 0.0

    if state == OPEN and breaker.opened_at:
        elapsed = time.time() - breaker.opened_at
        if elapsed >= cooldown_seconds:
            state = HALF_OPEN
            breaker.state = HALF_OPEN
        else:
            retry_in = cooldown_seconds - elapsed

    last_failure = None
    if breaker.last_failure_at:
        last_failure = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(breaker.last_failure_at)
        )

    return {
        "provider": provider,
        "state": state,
        "consecutive_failures": breaker.failures if state != OPEN else breaker.failures,
        "total_failures": breaker.total_failures,
        "last_failure_at": last_failure,
        "retry_in_s": round(retry_in, 1),
    }


def get_circuit_states() -> Dict[str, Dict[str, Any]]:
    """State for every configured provider, including those never called."""
    from lunair.config import settings

    states = {name: get_state(name) for name in settings.get_provider_status()}
    states.update({name: get_state(name) for name in _breakers})
    return states


def reset() -> None:
    _breakers.clear()