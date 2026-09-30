"""
strategy.base_strategy
~~~~~~~~~~~~~~~~~~~~~~
Abstract base class for all trading strategies in the NSE automated
trading system.

Subclasses must implement ``analyze()`` and ``should_exit()``.  Common
utilities such as position sizing and signal validation live here.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from core.models import Signal, SignalType


logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """Abstract base for every trading strategy.

    Parameters
    ----------
    name : str
        Human-readable strategy identifier (e.g. ``"EMA-Crossover-9-21"``).
    config : dict
        Strategy-specific configuration.  Sub-classes define which keys
        they require.
    """

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        self.name: str = name
        self.config: Dict[str, Any] = config
        self.logger: logging.Logger = logging.getLogger(
            f"{__name__}.{self.__class__.__name__}"
        )
        self.logger.info("Strategy '%s' initialised with config: %s", name, config)

    # ------------------------------------------------------------------
    # Abstract interface – must be implemented by every concrete strategy
    # ------------------------------------------------------------------

    @abstractmethod
    def analyze(self, market_data: dict) -> Optional[Signal]:
        """Analyse current market data and optionally emit a trading signal.

        Parameters
        ----------
        market_data : dict
            Opaque payload whose exact schema is strategy-specific.

        Returns
        -------
        Signal or None
            A ``Signal`` when conditions are met, otherwise ``None``.
        """

    @abstractmethod
    def should_exit(self, position: Any, market_data: dict) -> bool:
        """Determine whether an existing position should be closed.

        Parameters
        ----------
        position : Position (core.models.Position)
            The open position to evaluate.
        market_data : dict
            Latest market snapshot for the position's instrument.

        Returns
        -------
        bool
            ``True`` if the position should be exited immediately.
        """

    # ------------------------------------------------------------------
    # Common utilities
    # ------------------------------------------------------------------

    def calculate_position_size(
        self,
        capital: float,
        risk_pct: float,
        entry_price: float,
        stop_loss: float,
    ) -> int:
        """Calculate position size using fixed-fractional risk model.

        ``quantity = risk_amount / risk_per_share``

        Parameters
        ----------
        capital : float
            Available trading capital (₹).
        risk_pct : float
            Maximum percentage of capital to risk on the trade (e.g. 1.0
            means 1 %).
        entry_price : float
            Planned entry price per share.
        stop_loss : float
            Planned stop-loss price per share.

        Returns
        -------
        int
            Number of shares (always ≥ 0).  Returns 0 when the inputs
            make sizing impossible (e.g. stop_loss == entry_price).
        """
        if capital <= 0 or risk_pct <= 0:
            self.logger.warning(
                "Invalid sizing inputs: capital=%.2f, risk_pct=%.2f",
                capital,
                risk_pct,
            )
            return 0

        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share == 0:
            self.logger.warning(
                "Stop-loss equals entry price; cannot size position."
            )
            return 0

        risk_amount = capital * (risk_pct / 100.0)
        quantity = math.floor(risk_amount / risk_per_share)

        # Ensure we don't exceed available capital
        max_affordable = math.floor(capital / entry_price) if entry_price > 0 else 0
        quantity = min(quantity, max_affordable)
        quantity = max(quantity, 0)

        self.logger.debug(
            "Position size: capital=%.2f risk_pct=%.2f entry=%.2f sl=%.2f "
            "-> risk_per_share=%.2f risk_amt=%.2f qty=%d",
            capital,
            risk_pct,
            entry_price,
            stop_loss,
            risk_per_share,
            risk_amount,
            quantity,
        )
        return quantity

    def validate_signal(self, signal: Signal) -> bool:
        """Run basic sanity checks on a signal before it is published.

        Returns
        -------
        bool
            ``True`` if the signal passes all checks.
        """
        try:
            if not signal.symbol or not signal.symbol.strip():
                self.logger.warning("Signal rejected: empty symbol.")
                return False

            if signal.price <= 0:
                self.logger.warning(
                    "Signal rejected: non-positive price %.4f for %s.",
                    signal.price,
                    signal.symbol,
                )
                return False

            if not isinstance(signal.signal_type, SignalType):
                self.logger.warning(
                    "Signal rejected: invalid signal_type '%s'.",
                    signal.signal_type,
                )
                return False

            if not (0.0 <= signal.strength <= 1.0):
                self.logger.warning(
                    "Signal rejected: strength %.4f out of [0, 1] range.",
                    signal.strength,
                )
                return False

            return True
        except Exception:
            self.logger.exception("Unexpected error while validating signal.")
            return False
