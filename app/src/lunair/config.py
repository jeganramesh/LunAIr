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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LunAIR"
    version: str = "0.1.0"
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

    _yaml_cache: Optional[Dict[str, Any]] = None

    def get_yaml_config(self) -> Dict[str, Any]:
        if self._yaml_cache is not None:
            return self._yaml_cache

        # Look in relative paths from cwd or project root
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

    def get_provider_status(self) -> Dict[str, Dict[str, Any]]:
        """Report whether each configured provider has a usable API key.

        Returns ``{provider: {"configured": bool, "env_var": str, "model": str}}``.
        """
        status: Dict[str, Dict[str, Any]] = {}

        for item in self.get_model_list():
            params = item.get("litellm_params", {}) or {}
            litellm_model = params.get("model", "") or ""
            provider = litellm_model.split("/")[0] if "/" in litellm_model else litellm_model
            if not provider:
                continue

            env_var = PROVIDER_ENV_VARS.get(provider, f"{provider.upper()}_API_KEY")
            api_key = params.get("api_key") or os.getenv(env_var)
            status[provider] = {
                "configured": is_usable_api_key(api_key),
                "env_var": env_var,
                "model": litellm_model,
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
