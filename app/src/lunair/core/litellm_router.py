import os
from typing import Any, Dict, List, Optional
import litellm
from litellm import Router
from lunair.config import settings

# Optimize litellm initialization without remote network calls
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
litellm.suppress_debug_info = True


def create_router(
    model_list: Optional[List[Dict[str, Any]]] = None,
    fallbacks: Optional[List[Dict[str, List[str]]]] = None,
    num_retries: int = 2,
    timeout: int = 30,
) -> Router:
    """Create and configure a LiteLLM Router instance."""
    resolved_model_list = model_list if model_list is not None else settings.get_model_list()
    resolved_fallbacks = fallbacks if fallbacks is not None else settings.get_fallbacks()

    return Router(
        model_list=resolved_model_list,
        fallbacks=resolved_fallbacks,
        num_retries=num_retries,
        timeout=timeout,
    )


# Default singleton instance
router = create_router()
