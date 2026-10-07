"""Application bootstrap: load config, init DB, build the container."""

from __future__ import annotations

import logging

from app.core.container import AppContainer, build_container
from app.core.logging import setup_logging
from app.core.settings import settings
from app.infrastructure.config.config_models import AppConfig
from app.infrastructure.config.yaml_config_loader import YamlConfigLoader
from app.infrastructure.persistence.sqlite.connection import init_db

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> AppConfig:
    config_loader = YamlConfigLoader(config_path=config_path)
    raw = config_loader.load()
    return AppConfig.from_dict(raw)


def bootstrap(
    config_path: str | None = None,
    database_path: str | None = None,
    runtime_from: AppContainer | None = None,
) -> AppContainer:
    path = config_path or settings.config_path
    config = load_config(path)
    setup_logging(level=settings.log_level, structured=config.observability.structured_json_logs)

    logger.info("Bootstrapping %s in %s mode", config.gateway.name, config.gateway.environment)
    logger.info(
        "Config loaded: %d clients, %d providers, %d model profiles",
        len(config.clients),
        len(config.providers),
        len(config.model_profiles),
    )

    db_path = database_path or (
        runtime_from.db_path
        if runtime_from
        else (
            settings.database_url
            if settings.database_url.startswith(("postgresql://", "postgres://"))
            else settings.database_path
        )
    )
    if db_path.startswith(("postgresql://", "postgres://")):
        from app.infrastructure.persistence.postgresql.connection import migrate

        migrate(db_path)
        logger.info("PostgreSQL migrations applied")
    else:
        init_db(db_path)
        logger.info("SQLite database initialized at %s", db_path)

    container = build_container(config, db_path, previous=runtime_from)
    logger.info("Gateway ready with %d providers", len(container.providers))
    return container
