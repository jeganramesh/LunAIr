"""Per-key rate limiting backed by Redis.

Fixed-window counters per UTC minute:

* ``rl:req:<key>:<minute>`` — request count (checked pre-flight)
* ``rl:tok:<key>:<minute>`` — token count (estimated pre-flight, corrected
  after the response with the real usage)

If Redis is unavailable the limiter fails closed by default so a cache outage
cannot turn into an unbounded spend event. Set ``RATE_LIMIT_FAIL_CLOSED=false``
to fail open instead.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, List, Optional

from lunair.config import settings
from lunair.db.redis import get_redis

logger = logging.getLogger("lunair.ratelimit")

WINDOW_SECONDS = 60


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int = 0
    remaining: int = 0
    retry_after: int = 0
    reason: Optional[str] = None


def estimate_tokens(messages: List[Any]) -> int:
    """Rough prompt token estimate (~4 chars/token) for pre-flight admission."""
    chars = 0
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chars += len(part["text"])
    return max(1, chars // 4)


def _key(prefix: str, key_id: str, minute: int) -> str:
    return f"rl:{prefix}:{key_id}:{minute}"


async def check_rate_limit(
    key_id: str,
    rpm_limit: Optional[int],
    tpm_limit: Optional[int],
    estimated_tokens: int,
) -> RateLimitResult:
    # Nothing to enforce: skip Redis entirely.
    if not rpm_limit and not tpm_limit:
        return RateLimitResult(True)

    client = await get_redis()
    if client is None:
        if settings.rate_limit_fail_closed:
            return RateLimitResult(False, retry_after=1, reason="rate limiter unavailable")
        return RateLimitResult(True)

    now = time.time()
    minute = int(now // WINDOW_SECONDS)
    retry_after = WINDOW_SECONDS - int(now % WINDOW_SECONDS)

    try:
        req_key = _key("req", key_id, minute)
        tok_key = _key("tok", key_id, minute)

        req_count = await client.incr(req_key)
        await client.expire(req_key, WINDOW_SECONDS * 2)

        if rpm_limit and req_count > rpm_limit:
            return RateLimitResult(
                False, limit=rpm_limit, remaining=0,
                retry_after=retry_after, reason="requests per minute exceeded",
            )

        if tpm_limit:
            used = int(await client.get(tok_key) or 0)
            if used + estimated_tokens > tpm_limit:
                return RateLimitResult(
                    False, limit=tpm_limit, remaining=max(0, tpm_limit - used),
                    retry_after=retry_after, reason="tokens per minute exceeded",
                )

        remaining = (rpm_limit - req_count) if rpm_limit else 0
        return RateLimitResult(True, limit=rpm_limit or 0, remaining=max(0, remaining))
    except Exception as err:
        logger.warning("rate limit check failed: %s", type(err).__name__)
        if settings.rate_limit_fail_closed:
            return RateLimitResult(False, retry_after=1, reason="rate limiter error")
        return RateLimitResult(True)


async def record_tokens(key_id: str, tokens: int) -> None:
    """Add the real token usage to the current window's counter."""
    client = await get_redis()
    if client is None or tokens <= 0:
        return
    minute = int(time.time() // WINDOW_SECONDS)
    try:
        tok_key = _key("tok", key_id, minute)
        await client.incrby(tok_key, int(tokens))
        await client.expire(tok_key, WINDOW_SECONDS * 2)
    except Exception:
        pass
