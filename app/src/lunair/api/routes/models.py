import time
from typing import Any, Dict, List

from fastapi import APIRouter

from lunair.config import settings
from lunair.core.registry import load_registry

models_api = APIRouter(prefix="/v1", tags=["models"])

_RESERVED_ROUTING_KEYS = {"strategy", "auto_weights", "aliases"}


@models_api.get("/models")
async def list_models() -> Dict[str, Any]:
    registry = load_registry()
    current_time = int(time.time())

    model_entries: List[Dict[str, Any]] = []
    seen = set()

    for model_id in registry.models():
        endpoints = registry.endpoints_for(model_id)
        primary = endpoints[0] if endpoints else None
        seen.add(model_id)
        model_entries.append(
            {
                "id": model_id,
                "object": "model",
                "created": current_time,
                "owned_by": primary.provider if primary else "lunair",
                "context": primary.context if primary else None,
                "pricing": (
                    {"prompt": primary.price_in, "completion": primary.price_out}
                    if primary
                    else None
                ),
                "endpoints": [
                    {
                        "provider": e.provider,
                        "model": e.litellm_model,
                        "region": e.region,
                        "tier": e.tier,
                        "zdr": e.zdr,
                    }
                    for e in endpoints
                ],
            }
        )

    # Include auto/* alias pseudo-models from routing configuration.
    routing = settings.get_routing_config()
    aliases = dict(routing.get("aliases") or {})
    for key, value in routing.items():
        if key not in _RESERVED_ROUTING_KEYS and isinstance(value, list):
            aliases.setdefault(key, value)

    for alias in sorted(aliases.keys()):
        if alias not in seen:
            seen.add(alias)
            model_entries.append(
                {
                    "id": alias,
                    "object": "model",
                    "created": current_time,
                    "owned_by": "lunair",
                }
            )

    return {"object": "list", "data": model_entries}
