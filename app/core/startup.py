from __future__ import annotations

import logging

from app.core.logging import setup_logging
from app.core.settings import settings
from app.infrastructure.config.yaml_config_loader import YamlConfigLoader
from app.infrastructure.persistence.sqlite.connection import init_db

logger = logging.getLogger(__name__)


def bootstrap() -> None:
    setup_logging(level=settings.log_level)
    logger.info(
        "Bootstrapping %s in %s mode", settings.app_name, settings.environment
    )

    # Load config (validates the YAML file is present and parseable)
    config_loader = YamlConfigLoader(config_path=settings.config_path)
    config = config_loader.load()
    logger.info(
        "Config loaded: %d clients, %d providers, %d model profiles",
        len(config.get("clients", [])),
        len(config.get("providers", {})),
        len(config.get("model_profiles", {})),
    )

    # Initialize SQLite
    init_db(settings.database_path)
    logger.info("Database initialized at %s", settings.database_path)
