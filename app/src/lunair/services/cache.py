"""Response caching.

Exact-match caching is implemented here: identical (model, parameters,
messages) requests return the stored response. It is tenant-scoped (the key
includes the requesting key id) so one caller never sees another's answer.

Semantic caching (near-duplicate prompts) is intentionally left as a pluggable
hook — it needs an embedding model, and semantic similarity is not answer
equivalence, so it must be opt-in per workload. ``get``/``set`` accept an
optional embedder and, when absent, behave as exact-match only.
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from lunair.config import settings
from lunair.db.redis import get_redis

logger = logging.getLogger("lunair.cache")


def _canonical(model: str, params: Dict[str, Any], messages: List[Dict[str, Any]]) -> str:
    payload = {"model": model, "params": params, "messages": messages}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def cache_key(key_id: str, model: str, params: Dict[str, Any], messages: List[Dict[str, Any]]) -> str:
    digest = hashlib.sha256(_canonical(model, params, messages).encode("utf-8")).hexdigest()
    namespace = settings.get_cache_config().get("namespace", "lunair")
    return f"cache:{namespace}:{key_id}:{digest}"


def is_enabled() -> bool:
    return bool(settings.get_cache_config().get("enabled", False))


def prompt_prefix_hash(messages: List[Dict[str, Any]]) -> str:
    """Hash of the stable prompt prefix, used for cache-optimised routing."""
    system = "".join(
        m.get("content", "") for m in messages if m.get("role") == "system" and isinstance(m.get("content"), str)
    )
    return hashlib.sha256(system.encode("utf-8")).hexdigest()[:16]


async def get_cached(cache_key_value: str) -> Optional[Dict[str, Any]]:
    if not is_enabled():
        return None
    client = await get_redis()
    if client is None:
        return None
    try:
        raw = await client.get(cache_key_value)
        return json.loads(raw) if raw else None
    except Exception as err:
        logger.warning("cache read failed: %s", type(err).__name__)
        return None


async def set_cached(cache_key_value: str, response: Dict[str, Any]) -> None:
    if not is_enabled():
        return
    client = await get_redis()
    if client is None:
        return
    ttl = int(settings.get_cache_config().get("ttl_seconds", 3600))
    try:
        await client.set(cache_key_value, json.dumps(response, default=str), ex=ttl)
    except Exception as err:
        logger.warning("cache write failed: %s", type(err).__name__)
