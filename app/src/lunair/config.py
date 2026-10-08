from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()
