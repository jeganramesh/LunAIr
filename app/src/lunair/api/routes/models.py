import time
from typing import Any, Dict, List
from fastapi import APIRouter
from lunair.config import settings

models_api = APIRouter(prefix="/v1", tags=["models"])


@models_api.get("/models")
async def list_models() -> Dict[str, Any]:
    configured_models = settings.get_model_list()
    current_time = int(time.time())

    model_entries: List[Dict[str, Any]] = []
    seen = set()

    for item in configured_models:
        name = item.get("model_name")
        if name and name not in seen:
            seen.add(name)
            model_entries.append({
                "id": name,
                "object": "model",
                "created": current_time,
                "owned_by": item.get("litellm_params", {}).get("model", "custom").split("/")[0],
            })

    # Include auto/* pseudo-models from routing configuration
    for auto_model in settings.get_routing().keys():
        if auto_model not in seen:
            seen.add(auto_model)
            model_entries.append({
                "id": auto_model,
                "object": "model",
                "created": current_time,
                "owned_by": "lunair",
            })

    return {
        "object": "list",
        "data": model_entries,
    }
