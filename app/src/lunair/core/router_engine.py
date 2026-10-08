from typing import List, Optional
from lunair.config import settings


def resolve_intent(model_name: str, routing_config: Optional[dict] = None) -> List[str]:
    """
    Resolve model name intent to an ordered candidate model/provider list.
    
    If model_name is an auto alias (e.g. auto/cheap, auto/fast) defined in config,
    returns the list of candidate model names in priority order.
    Otherwise, returns [model_name] as a passthrough.
    """
    routing = routing_config if routing_config is not None else settings.get_routing()
    
    if model_name in routing:
        candidate_list = routing[model_name]
        if candidate_list:
            return list(candidate_list)
            
    # Default passthrough
    return [model_name]
