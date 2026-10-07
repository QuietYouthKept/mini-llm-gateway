from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigLoadError(Exception):
    """Raised when the YAML config cannot be loaded or parsed."""


class YamlConfigLoader:
    def __init__(self, config_path: str) -> None:
        self._config_path = Path(config_path)

    def load(self) -> dict[str, Any]:
        if not self._config_path.exists():
            raise ConfigLoadError(f"Config file not found: {self._config_path}")
        try:
            with open(self._config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ConfigLoadError(f"Failed to parse config YAML: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigLoadError("Config file must contain a YAML mapping")

        return data
