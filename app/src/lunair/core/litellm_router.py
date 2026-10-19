import os
from typing import Any, Dict, List, Optional
import litellm
from litellm import Router
from lunair.config import settings
from lunair.core.registry import load_registry

# Optimize litellm initialization without remote network calls
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
litellm.suppress_debug_info = True


def create_router(
    model_list: Optional[List[Dict[str, Any]]] = None,
    fallbacks: Optional[List[Dict[str, List[str]]]] = None,
    num_retries: int = 0,
    timeout: Optional[int] = None,
) -> Router:
    """Create and configure a LiteLLM Router instance.

    When ``model_list`` is not supplied it is derived from the endpoint
    registry, so every configured endpoint becomes a deployment.
    """
    resolved_model_list = model_list if model_list is not None else load_registry().litellm_model_list()
    resolved_fallbacks = fallbacks if fallbacks is not None else settings.get_fallbacks()
    resolved_timeout = timeout if timeout is not None else settings.upstream_timeout_seconds

    return Router(
        model_list=resolved_model_list,
        fallbacks=resolved_fallbacks,
        num_retries=num_retries,
        timeout=resolved_timeout,
    )


# Default singleton instance.
#
# Retries and fallbacks are handled explicitly in the chat handler so the two
# mechanisms cannot multiply. The router here is the provider abstraction; the
# routing *policy* lives in lunair.core.routing.
router = create_router(num_retries=0, fallbacks=[])
