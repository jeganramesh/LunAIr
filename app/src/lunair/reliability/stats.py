"""In-process routing telemetry.

Tracks per-deployment latency, success/failure and in-flight counts so the
router can make latency-, least-busy- and quality-aware decisions, and so the
auto-router can score endpoints.

This is deliberately in-process and best-effort: it is a *routing hint*, not a
source of truth. In a multi-replica deployment each replica scores from its own
recent traffic (a rolling window), which is sufficient for load balancing and
degrades gracefully. A shared (Redis) variant can be layered on later without
changing callers.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict

_WINDOW = 128


class _Tracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latency: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=_WINDOW))
        self._success: Dict[str, int] = defaultdict(int)
        self._failure: Dict[str, int] = defaultdict(int)
        self._last_success: Dict[str, float] = defaultdict(float)
        self._inflight: Dict[str, int] = defaultdict(int)

    def success(self, name: str, latency_ms: float) -> None:
        with self._lock:
            self._latency[name].append(latency_ms)
            self._success[name] += 1
            self._last_success[name] = time.time()

    def failure(self, name: str) -> None:
        with self._lock:
            self._failure[name] += 1

    def inc_inflight(self, name: str) -> None:
        with self._lock:
            self._inflight[name] += 1

    def dec_inflight(self, name: str) -> None:
        with self._lock:
            if self._inflight[name] > 0:
                self._inflight[name] -= 1

    def snapshot(self, name: str) -> Dict[str, Any]:
        with self._lock:
            latencies = sorted(self._latency.get(name, ()))
            success = self._success.get(name, 0)
            failure = self._failure.get(name, 0)
            total = success + failure
            p95 = latencies[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))] if latencies else None
            avg = (sum(latencies) / len(latencies)) if latencies else None
            return {
                "samples": len(latencies),
                "p95_ms": p95,
                "avg_ms": avg,
                "success": success,
                "failure": failure,
                "success_rate": (success / total) if total else None,
                "last_success_ts": self._last_success.get(name) or None,
                "inflight": self._inflight.get(name, 0),
            }

    def reset(self) -> None:
        with self._lock:
            self._latency.clear()
            self._success.clear()
            self._failure.clear()
            self._last_success.clear()
            self._inflight.clear()


_tracker = _Tracker()


def record_success(name: str, latency_ms: float) -> None:
    _tracker.success(name, latency_ms)


def record_failure(name: str) -> None:
    _tracker.failure(name)


def inc_inflight(name: str) -> None:
    _tracker.inc_inflight(name)


def dec_inflight(name: str) -> None:
    _tracker.dec_inflight(name)


def snapshot(name: str) -> Dict[str, Any]:
    return _tracker.snapshot(name)


def reset() -> None:
    _tracker.reset()
