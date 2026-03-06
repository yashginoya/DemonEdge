import os
from typing import Any

import yaml

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml")


class _Config:
    """Singleton config reader. Reads config/settings.yaml on first access."""

    _instance: "_Config | None" = None
    _data: dict | None = None

    def __new__(cls) -> "_Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _load(self) -> None:
        if self._data is not None:
            return
        if not os.path.exists(_CONFIG_PATH):
            raise FileNotFoundError(
                "config/settings.yaml not found. "
                "Copy config/settings.example.yaml and fill in your credentials."
            )
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}

    def get(self, key: str, default: Any = None) -> Any:
        """Dot-notation access. e.g. Config.get('broker.api_key')"""
        self._load()
        parts = key.split(".")
        value: Any = self._data
        for part in parts:
            if not isinstance(value, dict):
                return default
            value = value.get(part)
            if value is None:
                return default
        return value


Config = _Config()
