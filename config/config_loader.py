"""
config.config_loader
~~~~~~~~~~~~~~~~~~~~
Centralised, singleton configuration loader for the trading system.

Features
--------
* Loads ``settings.yaml`` with full YAML support.
* Environment-variable overrides (``BROKER_USER_ID`` → ``broker.user_id``).
* Optional ``.env`` file support (auto-detected in project root).
* Dot-notation ``get()`` with default values.
* Required-field validation on load.
* Thread-safe singleton via ``__new__``.
* ``reload()`` for live config refresh.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Fields that must be present and non-empty for the system to start.
_REQUIRED_FIELDS: List[str] = [
    "broker.user_id",
    "broker.api_key",
    "trading.exchange",
    "trading.capital_per_trade",
]

# Mapping: environment variable name → dot-notation config key.
_ENV_OVERRIDES: Dict[str, str] = {
    "BROKER_USER_ID": "broker.user_id",
    "BROKER_API_KEY": "broker.api_key",
    "TRADING_EXCHANGE": "trading.exchange",
    "TRADING_MAX_POSITIONS": "trading.max_positions",
    "TRADING_MAX_ORDER_VALUE": "trading.max_order_value",
    "TRADING_CAPITAL_PER_TRADE": "trading.capital_per_trade",
    "LOG_LEVEL": "logging.level",
    "TELEGRAM_BOT_TOKEN": "notifications.telegram_bot_token",
    "TELEGRAM_CHAT_ID": "notifications.telegram_chat_id",
}


class ConfigLoader:
    """Singleton configuration manager.

    Usage
    -----
    >>> cfg = ConfigLoader()                        # uses default path
    >>> cfg = ConfigLoader("path/to/settings.yaml") # explicit path
    >>> cfg.get("broker.user_id")
    >>> cfg.get("risk_management.max_loss_per_trade_pct", default=2.0)
    >>> cfg.reload()
    """

    _instance: Optional[ConfigLoader] = None
    _lock: threading.Lock = threading.Lock()
    _initialised: bool = False

    # ------------------------------------------------------------------ #
    # Singleton
    # ------------------------------------------------------------------ #

    def __new__(cls, config_path: Optional[str] = None) -> ConfigLoader:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, config_path: Optional[str] = None) -> None:
        if self._initialised and config_path is None:
            return
        self._config_path = self._resolve_path(config_path)
        self._data: Dict[str, Any] = {}
        self._load()
        self.__class__._initialised = True

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value using dot-notation.

        Parameters
        ----------
        key : str
            Dot-separated path, e.g. ``"broker.user_id"``.
        default : Any
            Returned when the key does not exist.

        Returns
        -------
        Any
            The configuration value or *default*.
        """
        keys = key.split(".")
        node: Any = self._data
        for part in keys:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, key: str, value: Any) -> None:
        """Set a value at the given dot-notation path (runtime only)."""
        keys = key.split(".")
        node = self._data
        for part in keys[:-1]:
            node = node.setdefault(part, {})
        node[keys[-1]] = value

    def reload(self) -> None:
        """Re-read the YAML file and re-apply environment overrides."""
        logger.info("Reloading configuration from %s", self._config_path)
        self._load()

    @property
    def data(self) -> Dict[str, Any]:
        """Return a shallow copy of the raw config dict."""
        return dict(self._data)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resolve_path(config_path: Optional[str]) -> Path:
        """Resolve the settings file path.

        Priority:
        1. Explicit *config_path* argument.
        2. ``CONFIG_PATH`` environment variable.
        3. ``config/settings.yaml`` relative to this file's parent directory.
        """
        if config_path:
            return Path(config_path).resolve()

        env_path = os.environ.get("CONFIG_PATH")
        if env_path:
            return Path(env_path).resolve()

        return (Path(__file__).resolve().parent / "settings.yaml")

    def _load(self) -> None:
        """Load YAML, apply env overrides, validate."""
        self._load_dotenv()
        self._data = self._read_yaml()
        self._apply_env_overrides()
        self._validate()
        logger.info("Configuration loaded successfully from %s", self._config_path)

    def _read_yaml(self) -> Dict[str, Any]:
        if not self._config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {self._config_path}"
            )
        with open(self._config_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise ValueError(
                f"Expected a YAML mapping at top level, got {type(data).__name__}"
            )
        return data

    def _load_dotenv(self) -> None:
        """Load a ``.env`` file from the project root if it exists."""
        env_file = self._config_path.parent.parent / ".env"
        if not env_file.exists():
            return
        logger.debug("Loading .env from %s", env_file)
        with open(env_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                var, _, val = line.partition("=")
                var = var.strip()
                val = val.strip().strip("\"'")
                os.environ.setdefault(var, val)

    def _apply_env_overrides(self) -> None:
        """Override YAML values with matching environment variables."""
        for env_var, dot_key in _ENV_OVERRIDES.items():
            value = os.environ.get(env_var)
            if value is not None:
                # Attempt type coercion to int / float where appropriate.
                coerced = self._coerce(value)
                self.set(dot_key, coerced)
                logger.debug("Env override applied: %s → %s", env_var, dot_key)

    def _validate(self) -> None:
        """Ensure required fields are present and non-placeholder."""
        missing: List[str] = []
        for key in _REQUIRED_FIELDS:
            val = self.get(key)
            if val is None or str(val).startswith("YOUR_"):
                missing.append(key)
        if missing:
            logger.warning(
                "The following required config fields are missing or still have "
                "placeholder values: %s. Set them in settings.yaml or via "
                "environment variables before starting live trading.",
                ", ".join(missing),
            )

    @staticmethod
    def _coerce(value: str) -> Any:
        """Best-effort coercion of string env values to native types."""
        if value.lower() in ("true", "yes"):
            return True
        if value.lower() in ("false", "no"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value

    # ------------------------------------------------------------------ #
    # Dunder helpers
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        return f"<ConfigLoader path='{self._config_path}'>"

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None
