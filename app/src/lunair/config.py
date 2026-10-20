from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROVIDER_ENV_VARS: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

# Values shipped in .env.example that must never be treated as real credentials.
PLACEHOLDER_MARKERS = (
    "REPLACE_ME",
    "CHANGE_ME",
    "REPLACE_WITH",
    "YOUR_KEY",
    "SK-XXX",
)


def is_usable_api_key(value: Optional[str]) -> bool:
    """Return True only for a non-placeholder credential."""
    if not value:
        return False
    candidate = value.strip()
    if not candidate:
        return False
    return not any(marker in candidate.upper() for marker in PLACEHOLDER_MARKERS)


def provider_env_var(provider: str) -> str:
    """Environment variable that holds a provider's credential."""
    return PROVIDER_ENV_VARS.get(provider, f"{provider.upper()}_API_KEY")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LunAIR"
    version: str = "0.2.0"
    debug: bool = False

    gateway_mode: str = Field(default="go", alias="GATEWAY_MODE")
    fastapi_url: str = Field(default="http://localhost:8000", alias="FASTAPI_URL")
    gateway_port: int = Field(default=8080, alias="GATEWAY_PORT")

    database_url: str = Field(
        default="postgresql+asyncpg://lunair:CHANGE_ME@localhost:5432/lunair",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    groq_api_key: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    septr_api_key: Optional[str] = Field(default=None, alias="SEPTR_API_KEY")

    config_path: str = Field(default="config/config.yaml", alias="CONFIG_PATH")

    # Comma-separated allowed origins. Empty falls back to local dev ports.
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        alias="CORS_ORIGINS",
    )

    # Retention window for request-log partitions, in days.
    retention_days: int = Field(default=30, alias="RETENTION_DAYS")

    # --- Security -------------------------------------------------------
    # Shared secret the Go gateway presents on requests it forwards. Without
    # it, the core refuses to honour the trusted-header path.
    gateway_shared_secret: Optional[str] = Field(default=None, alias="GATEWAY_SHARED_SECRET")
    # Admin key that unlocks the key-management API. Unset => API disabled.
    admin_api_key: Optional[str] = Field(default=None, alias="LUNAIR_ADMIN_KEY")
    # Local-development auth bypass. MUST stay false outside development.
    dev_auth_bypass: bool = Field(default=False, alias="DEV_AUTH_BYPASS")

    # --- Limits & budgets ----------------------------------------------
    rate_limit_fail_closed: bool = Field(default=True, alias="RATE_LIMIT_FAIL_CLOSED")
    budget_fail_closed: bool = Field(default=True, alias="BUDGET_FAIL_CLOSED")
    budget_enforcement: bool = Field(default=True, alias="BUDGET_ENFORCEMENT")

    # --- Timeouts -------------------------------------------------------
    upstream_timeout_seconds: int = Field(default=30, alias="UPSTREAM_TIMEOUT_SECONDS")
    request_timeout_seconds: int = Field(default=120, alias="REQUEST_TIMEOUT_SECONDS")

    # Number of months of request partitions to keep provisioned ahead.
    partition_months_ahead: int = Field(default=3, alias="PARTITION_MONTHS_AHEAD")

    _yaml_cache: Optional[Dict[str, Any]] = None
    _provider_map: Optional[Dict[str, str]] = None
    _litellm_map: Optional[Dict[str, str]] = None

    # --- config.yaml access --------------------------------------------
    def get_yaml_config(self) -> Dict[str, Any]:
        if self._yaml_cache is not None:
            return self._yaml_cache

        candidates = [
            Path(self.config_path),
            Path("../") / self.config_path,
            Path(__file__).resolve().parents[3] / "config" / "config.yaml",
        ]

        cfg_file = None
        for candidate in candidates:
            if candidate.is_file():
                cfg_file = candidate
                break

        if cfg_file is None:
            self._yaml_cache = {}
            return self._yaml_cache

        with open(cfg_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            self._yaml_cache = data
            return self._yaml_cache

    def get_model_list(self) -> List[Dict[str, Any]]:
        raw_list = self.get_yaml_config().get("model_list", [])
        resolved_list = []
        for item in raw_list:
            item_copy = dict(item)
            litellm_params = dict(item_copy.get("litellm_params", {}))
            api_key = litellm_params.get("api_key")
            if isinstance(api_key, str) and api_key.startswith("os.environ/"):
                env_var = api_key.split("/", 1)[1]
                litellm_params["api_key"] = os.getenv(env_var, "")
            item_copy["litellm_params"] = litellm_params
            resolved_list.append(item_copy)
        return resolved_list

    def get_fallbacks(self) -> List[Dict[str, List[str]]]:
        return self.get_yaml_config().get("router_settings", {}).get("fallbacks", [])

    def get_routing(self) -> Dict[str, List[str]]:
        return self.get_yaml_config().get("routing", {})

    def get_gateway_config(self) -> Dict[str, Any]:
        return self.get_yaml_config().get("gateway", {}) or {}

    def get_rate_limit_config(self) -> Dict[str, Any]:
        return self.get_gateway_config().get("rate_limit", {}) or {}

    def get_circuit_breaker_config(self) -> Dict[str, Any]:
        return self.get_gateway_config().get("circuit_breaker", {}) or {}

    def get_budget_config(self) -> Dict[str, Any]:
        return self.get_yaml_config().get("budgets", {}) or {}

    def get_security_config(self) -> Dict[str, Any]:
        return self.get_yaml_config().get("security", {}) or {}

    def get_models_config(self) -> Dict[str, Any]:
        """Explicit ``models:`` block, or ``{}`` when the legacy list is used."""
        return self.get_yaml_config().get("models", {}) or {}

    def get_routing_config(self) -> Dict[str, Any]:
        """Full routing section: default strategy, aliases, auto weights."""
        return self.get_yaml_config().get("routing", {}) or {}

    def get_cache_config(self) -> Dict[str, Any]:
        return self.get_yaml_config().get("semantic_cache", {}) or {}

    def get_compression_config(self) -> Dict[str, Any]:
        return self.get_yaml_config().get("compression", {}) or {}

    # --- provider / model resolution -----------------------------------
    def _registry(self):
        # Imported lazily to avoid a config <-> registry import cycle.
        from lunair.core.registry import load_registry

        return load_registry()

    def provider_for_model(self, model_name: str) -> str:
        """Resolve the provider serving a model, using config then heuristics."""
        endpoints = self._registry().endpoints_for(model_name)
        if endpoints:
            return endpoints[0].provider

        lowered = model_name.lower()
        if "gemini" in lowered:
            return "gemini"
        if "groq" in lowered or "llama" in lowered:
            return "groq"
        if "gpt" in lowered or lowered.startswith("o1") or lowered.startswith("o3"):
            return "openai"
        if "claude" in lowered:
            return "anthropic"
        return "openai"

    def litellm_model_for(self, model_name: str) -> str:
        """Return the fully-qualified LiteLLM model id for a configured alias."""
        endpoints = self._registry().endpoints_for(model_name)
        if endpoints:
            return endpoints[0].litellm_model
        return model_name

    def get_provider_credentials(self) -> Dict[str, str]:
        """Map provider -> credential, read from the environment.

        Used for provider calls the core makes itself (e.g. balance lookups)
        that need the same credential the router uses.
        """
        creds: Dict[str, str] = {}
        for endpoint in self._registry().all_endpoints():
            if endpoint.api_key:
                creds[endpoint.provider] = endpoint.api_key
        # Also expose providers referenced only by the balance config.
        for entry in self.get_yaml_config().get("balance", {}).get("providers", []) or []:
            name = entry.get("name")
            if name and name not in creds:
                value = os.getenv(provider_env_var(name), "")
                if value:
                    creds[name] = value
        return creds

    # --- provider health reporting -------------------------------------
    def get_provider_status(self) -> Dict[str, Dict[str, Any]]:
        """Report whether each configured provider has a usable API key.

        Returns ``{provider: {"configured": bool, "env_var": str, "model": str}}``.
        """
        status: Dict[str, Dict[str, Any]] = {}

        for endpoint in self._registry().all_endpoints():
            status[endpoint.provider] = {
                "configured": is_usable_api_key(endpoint.api_key),
                "env_var": provider_env_var(endpoint.provider),
                "model": endpoint.litellm_model,
            }

        return status

    def get_unconfigured_providers(self) -> Dict[str, str]:
        """Return ``{provider: env_var}`` for providers missing a real API key."""
        return {
            provider: info["env_var"]
            for provider, info in self.get_provider_status().items()
            if not info["configured"]
        }


settings = Settings()
