from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "mini-llm-gateway"
    environment: str = "local"
    config_path: str = "config/config.yaml"
    database_url: str = "sqlite:///data/gateway.db"
    database_path: str = "data/gateway.db"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    model_config = {"env_prefix": "GW_", "case_sensitive": False}


settings = Settings()
