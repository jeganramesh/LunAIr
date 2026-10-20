"""Endpoint registry — the two-layer routing model.

A *model* (e.g. ``gpt-4o-mini``) can be served by many *endpoints*, each being a
``(provider, upstream model, region, tier)`` tuple with its own pricing and
capabilities. Routing operates on endpoints, not models, which is what makes
load balancing, price/latency sorting, failover and data-policy routing
possible.

Configuration is read from ``config.yaml``. Two shapes are supported:

* **New** — an explicit ``models:`` block::

      models:
        gpt-4o-mini:
          endpoints:
            - provider: openai
              model: openai/gpt-4o-mini
              price_in: 0.15
              price_out: 0.60

* **Legacy** — the original ``model_list:``, where each entry is a single
  endpoint. This keeps existing deployments working unchanged.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from lunair.config import provider_env_var, settings


def _resolve_secret(value: Optional[str]) -> Optional[str]:
    if isinstance(value, str) and value.startswith("os.environ/"):
        import os

        return os.getenv(value.split("/", 1)[1], "")
    return value


@dataclass(frozen=True)
class Endpoint:
    model_id: str
    provider: str
    litellm_model: str
    deployment_name: str
    price_in: Optional[float] = None       # USD per 1M prompt tokens
    price_out: Optional[float] = None      # USD per 1M completion tokens
    context: Optional[int] = None
    region: Optional[str] = None
    tier: str = "default"
    zdr: bool = False
    weight: float = 1.0
    api_key: Optional[str] = None
    api_base: Optional[str] = None

    @property
    def blended_price(self) -> float:
        """Rough per-1M price used for cost sorting when usage is unknown."""
        return (self.price_in or 0.0) + (self.price_out or 0.0)

    def litellm_params(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {"model": self.litellm_model}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.api_base:
            params["api_base"] = self.api_base
        return params


class ModelRegistry:
    """Immutable index of models and their endpoints."""

    def __init__(self, by_model: Dict[str, List[Endpoint]]):
        self._by_model = by_model
        self._by_deployment = {
            ep.deployment_name: ep
            for endpoints in by_model.values()
            for ep in endpoints
        }

    # --- construction ---------------------------------------------------
    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "ModelRegistry":
        models_cfg = cfg.get("models")
        if models_cfg:
            return cls(cls._parse_models(models_cfg))
        return cls(cls._parse_model_list(cfg.get("model_list", []) or []))

    @staticmethod
    def _deployment_name(model_id: str, provider: str, region: Optional[str], index: int, total: int) -> str:
        if total == 1:
            return model_id
        suffix = provider if not region else f"{provider}:{region}"
        return f"{model_id}::{suffix}" if index >= 0 else f"{model_id}::{suffix}"

    @classmethod
    def _parse_models(cls, models_cfg: Dict[str, Any]) -> Dict[str, List[Endpoint]]:
        by_model: Dict[str, List[Endpoint]] = {}
        for model_id, spec in models_cfg.items():
            raw_endpoints = (spec or {}).get("endpoints", []) or []
            endpoints: List[Endpoint] = []
            total = len(raw_endpoints)
            for idx, entry in enumerate(raw_endpoints):
                provider = entry.get("provider") or (entry.get("model", "").split("/")[0])
                litellm_model = entry.get("model", "")
                region = entry.get("region")
                deployment = entry.get("deployment_name") or cls._deployment_name(
                    model_id, provider, region, idx, total
                )
                endpoints.append(
                    Endpoint(
                        model_id=model_id,
                        provider=provider,
                        litellm_model=litellm_model,
                        deployment_name=deployment,
                        price_in=_to_float(entry.get("price_in")),
                        price_out=_to_float(entry.get("price_out")),
                        context=_to_int(entry.get("context")),
                        region=region,
                        tier=entry.get("tier", "default"),
                        zdr=bool(entry.get("zdr", False)),
                        weight=_to_float(entry.get("weight")) or 1.0,
                        api_key=_resolve_secret(entry.get("api_key")) or _env_key(provider),
                        api_base=entry.get("api_base"),
                    )
                )
            if endpoints:
                by_model[model_id] = endpoints
        return by_model

    @classmethod
    def _parse_model_list(cls, model_list: List[Dict[str, Any]]) -> Dict[str, List[Endpoint]]:
        by_model: Dict[str, List[Endpoint]] = {}
        for entry in model_list:
            model_id = entry.get("model_name")
            params = entry.get("litellm_params", {}) or {}
            litellm_model = params.get("model", "")
            if not model_id or not litellm_model:
                continue
            provider = litellm_model.split("/")[0] if "/" in litellm_model else litellm_model
            api_key = _resolve_secret(params.get("api_key")) or _env_key(provider)
            by_model.setdefault(model_id, []).append(
                Endpoint(
                    model_id=model_id,
                    provider=provider,
                    litellm_model=litellm_model,
                    deployment_name=model_id,
                    api_key=api_key,
                    api_base=params.get("api_base"),
                )
            )
        return by_model

    # --- queries --------------------------------------------------------
    def endpoints_for(self, model_id: str) -> List[Endpoint]:
        return list(self._by_model.get(model_id, []))

    def models(self) -> List[str]:
        return sorted(self._by_model.keys())

    def get_endpoint(self, deployment_name: str) -> Optional[Endpoint]:
        return self._by_deployment.get(deployment_name)

    def deployment_names(self) -> List[str]:
        return list(self._by_deployment.keys())

    def all_endpoints(self) -> List[Endpoint]:
        return list(self._by_deployment.values())

    def litellm_model_list(self) -> List[Dict[str, Any]]:
        """Flatten every endpoint into a LiteLLM deployment list."""
        return [
            {"model_name": ep.deployment_name, "litellm_params": ep.litellm_params()}
            for ep in self._by_deployment.values()
        ]


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _env_key(provider: str) -> Optional[str]:
    import os

    return os.getenv(provider_env_var(provider)) or None


def load_registry() -> ModelRegistry:
    """Build the registry from the active configuration."""
    return ModelRegistry.from_config(settings.get_yaml_config())
