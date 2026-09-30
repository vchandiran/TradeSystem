"""
risk.risk_manager
~~~~~~~~~~~~~~~~~
Comprehensive risk management engine for the NSE automated trading system.

Enforces pre-trade and intra-day risk limits including per-trade loss caps,
daily drawdown limits, position limits, market-hours gating, and trailing
stop-loss management.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default risk parameters (can be overridden via config)
# ---------------------------------------------------------------------------

_DEFAULT_RISK_CONFIG: Dict[str, Any] = {
    "max_loss_per_trade": 1000.0,       # ₹ absolute cap per trade
    "daily_loss_limit": 5000.0,         # ₹ maximum aggregate daily loss
    "max_positions": 5,                 # simultaneous open positions
    "max_order_value": 500_000.0,       # ₹ single-order notional cap
    "max_drawdown_pct": 5.0,            # % drawdown from peak capital
    "risk_per_trade_pct": 1.0,          # % of capital risked per trade
    "default_stop_loss_pct": 1.5,       # % default stop-loss distance
    "default_risk_reward": 2.0,         # default risk-to-reward ratio
    "trailing_stop_pct": 0.5,           # % trailing-stop step
    "market_open": "09:15",             # IST
    "market_close": "15:30",            # IST
    "max_trades_per_day": 20,
    "initial_capital": 100_000.0,
}


class RiskManager:
    """Central risk-management gate for the trading system.

    Every order request is validated against configurable limits before it
    reaches the broker.  The manager also tracks daily P&L, drawdown, and
    provides position-sizing and stop-loss utilities.
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, config: dict) -> None:
        # Merge caller config on top of defaults
        self._cfg: Dict[str, Any] = {**_DEFAULT_RISK_CONFIG, **config}

        # Parse market hours once
        h, m = map(int, str(self._cfg["market_open"]).split(":"))
        self._market_open = time(h, m)
        h, m = map(int, str(self._cfg["market_close"]).split(":"))
        self._market_close = time(h, m)

        # Daily tracking state
        self._daily_pnl: float = 0.0
        self._total_trades_today: int = 0
        self._winning_trades: int = 0
        self._losing_trades: int = 0
        self._open_positions: int = 0

        # Drawdown tracking
        self._initial_capital: float = float(self._cfg["initial_capital"])
        self._peak_capital: float = self._initial_capital
        self._current_capital: float = self._initial_capital
        self._max_drawdown: float = 0.0

        # Thread safety for concurrent signal handlers
        self._lock = threading.Lock()

        logger.info(
            "RiskManager initialised – daily_loss_limit=%.2f  max_positions=%d  "
            "max_order_value=%.2f  max_drawdown_pct=%.2f%%",
            self._cfg["daily_loss_limit"],
            self._cfg["max_positions"],
            self._cfg["max_order_value"],
            self._cfg["max_drawdown_pct"],
        )

    # ------------------------------------------------------------------
    # Order validation
    # ------------------------------------------------------------------

    def validate_order(self, order_request: dict) -> Tuple[bool, str]:
        """Validate an order request against all risk limits.

        Parameters
        ----------
        order_request : dict
            Must contain at minimum ``price``, ``quantity``, and ``side``.

        Returns
        -------
        tuple[bool, str]
            ``(True, "")`` when the order passes; ``(False, reason)`` otherwise.
        """
        with self._lock:
            # 1. Market hours -------------------------------------------
            allowed, reason = self.is_trading_allowed()
            if not allowed:
                logger.warning("Order rejected – %s", reason)
                return False, reason

            price = float(order_request.get("price", 0))
            quantity = int(order_request.get("quantity", 0))
            order_value = price * quantity

            # 2. Max order value ----------------------------------------
            if order_value > self._cfg["max_order_value"]:
                reason = (
                    f"Order value ₹{order_value:,.2f} exceeds limit "
                    f"₹{self._cfg['max_order_value']:,.2f}"
                )
                logger.warning("Order rejected – %s", reason)
                return False, reason

            # 3. Max loss per trade -------------------------------------
            stop_loss_amount = float(order_request.get(
                "stop_loss_amount",
                price * quantity * self._cfg["default_stop_loss_pct"] / 100,
            ))
            if stop_loss_amount > self._cfg["max_loss_per_trade"]:
                reason = (
                    f"Potential loss ₹{stop_loss_amount:,.2f} exceeds per-trade "
                    f"limit ₹{self._cfg['max_loss_per_trade']:,.2f}"
                )
                logger.warning("Order rejected – %s", reason)
                return False, reason

            # 4. Daily loss limit ---------------------------------------
            if self._daily_pnl < 0 and abs(self._daily_pnl) >= self._cfg["daily_loss_limit"]:
                reason = (
                    f"Daily loss limit breached – current P&L ₹{self._daily_pnl:,.2f}, "
                    f"limit ₹{self._cfg['daily_loss_limit']:,.2f}"
                )
                logger.warning("Order rejected – %s", reason)
                return False, reason

            # 5. Max positions ------------------------------------------
            if self._open_positions >= self._cfg["max_positions"]:
                reason = (
                    f"Max open positions ({self._cfg['max_positions']}) reached"
                )
                logger.warning("Order rejected – %s", reason)
                return False, reason

            # 6. Max drawdown -------------------------------------------
            drawdown_pct = self._compute_drawdown_pct()
            if drawdown_pct >= self._cfg["max_drawdown_pct"]:
                reason = (
                    f"Max drawdown {drawdown_pct:.2f}% breached "
                    f"(limit {self._cfg['max_drawdown_pct']:.2f}%)"
                )
                logger.warning("Order rejected – %s", reason)
                return False, reason

            # 7. Max trades per day -------------------------------------
            if self._total_trades_today >= self._cfg["max_trades_per_day"]:
                reason = (
                    f"Max trades per day ({self._cfg['max_trades_per_day']}) reached"
                )
                logger.warning("Order rejected – %s", reason)
                return False, reason

            logger.debug(
                "Order validated – value=₹%.2f  positions=%d  daily_pnl=₹%.2f",
                order_value, self._open_positions, self._daily_pnl,
            )
            return True, ""

    # ------------------------------------------------------------------
    # Stop-loss / target helpers
    # ------------------------------------------------------------------

    def calculate_stop_loss(
        self,
        entry_price: float,
        side: str,
        stop_pct: Optional[float] = None,
    ) -> float:
        """Return absolute stop-loss price.

        Parameters
        ----------
        entry_price : float
            Trade entry price.
        side : str
            ``"BUY"`` or ``"SELL"``.
        stop_pct : float, optional
            Percentage distance for the stop.  Falls back to
            ``default_stop_loss_pct`` from config.
        """
        pct = stop_pct if stop_pct is not None else self._cfg["default_stop_loss_pct"]
        distance = entry_price * pct / 100

        if side.upper() == "BUY":
            stop = entry_price - distance
        else:
            stop = entry_price + distance

        stop = round(stop, 2)
        logger.debug(
            "Stop-loss calculated – entry=%.2f  side=%s  pct=%.2f%%  stop=%.2f",
            entry_price, side, pct, stop,
        )
        return stop

    def calculate_target(
        self,
        entry_price: float,
        side: str,
        risk_reward_ratio: float = 2.0,
        stop_pct: Optional[float] = None,
    ) -> float:
        """Return target price based on risk-reward ratio.

        The stop-loss distance is multiplied by ``risk_reward_ratio`` to
        determine the target distance from entry.
        """
        pct = stop_pct if stop_pct is not None else self._cfg["default_stop_loss_pct"]
        distance = entry_price * pct / 100 * risk_reward_ratio

        if side.upper() == "BUY":
            target = entry_price + distance
        else:
            target = entry_price - distance

        target = round(target, 2)
        logger.debug(
            "Target calculated – entry=%.2f  side=%s  rr=%.1f  target=%.2f",
            entry_price, side, risk_reward_ratio, target,
        )
        return target

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def calculate_position_size(
        self,
        capital: float,
        risk_per_trade_pct: float,
        entry_price: float,
        stop_loss: float,
    ) -> int:
        """Compute the number of shares to trade.

        Uses a fixed-fractional model: ``risk_amount / per_share_risk``.
        The result is always ≥ 0 (returns 0 when the numbers don't make
        sense, e.g. stop_loss == entry_price).
        """
        risk_amount = capital * risk_per_trade_pct / 100
        per_share_risk = abs(entry_price - stop_loss)

        if per_share_risk <= 0:
            logger.warning(
                "Invalid per-share risk (entry=%.2f, sl=%.2f) – returning 0",
                entry_price, stop_loss,
            )
            return 0

        size = int(risk_amount / per_share_risk)

        # Cap against max order value
        max_qty_by_value = int(self._cfg["max_order_value"] / entry_price) if entry_price > 0 else 0
        size = min(size, max_qty_by_value)

        logger.debug(
            "Position size – capital=%.2f  risk_pct=%.2f%%  entry=%.2f  "
            "sl=%.2f  size=%d",
            capital, risk_per_trade_pct, entry_price, stop_loss, size,
        )
        return max(size, 0)

    # ------------------------------------------------------------------
    # Daily P&L tracking
    # ------------------------------------------------------------------

    def update_daily_pnl(self, pnl: float) -> None:
        """Record a closed-trade P&L and update all running metrics."""
        with self._lock:
            self._daily_pnl += pnl
            self._total_trades_today += 1

            if pnl >= 0:
                self._winning_trades += 1
            else:
                self._losing_trades += 1

            # Update capital and drawdown
            self._current_capital += pnl
            if self._current_capital > self._peak_capital:
                self._peak_capital = self._current_capital

            dd = self._compute_drawdown_pct()
            if dd > self._max_drawdown:
                self._max_drawdown = dd

            logger.info(
                "P&L updated – trade_pnl=₹%.2f  daily_pnl=₹%.2f  "
                "trades=%d (W:%d / L:%d)  drawdown=%.2f%%",
                pnl, self._daily_pnl, self._total_trades_today,
                self._winning_trades, self._losing_trades, dd,
            )

    def set_open_positions(self, count: int) -> None:
        """Externally set the number of open positions (e.g. from broker sync)."""
        with self._lock:
            self._open_positions = count
            logger.debug("Open positions updated to %d", count)

    def increment_open_positions(self) -> None:
        """Increment the open-position counter by one."""
        with self._lock:
            self._open_positions += 1

    def decrement_open_positions(self) -> None:
        """Decrement the open-position counter by one (floor at 0)."""
        with self._lock:
            self._open_positions = max(0, self._open_positions - 1)

    # ------------------------------------------------------------------
    # Risk metrics
    # ------------------------------------------------------------------

    def get_risk_metrics(self) -> Dict[str, Any]:
        """Return a snapshot of all tracked risk metrics."""
        with self._lock:
            win_rate = (
                (self._winning_trades / self._total_trades_today * 100)
                if self._total_trades_today > 0
                else 0.0
            )
            return {
                "daily_pnl": round(self._daily_pnl, 2),
                "total_trades_today": self._total_trades_today,
                "winning_trades": self._winning_trades,
                "losing_trades": self._losing_trades,
                "win_rate_pct": round(win_rate, 2),
                "open_positions": self._open_positions,
                "current_capital": round(self._current_capital, 2),
                "peak_capital": round(self._peak_capital, 2),
                "max_drawdown_pct": round(self._max_drawdown, 2),
                "current_drawdown_pct": round(self._compute_drawdown_pct(), 2),
                "daily_loss_limit": self._cfg["daily_loss_limit"],
                "daily_loss_remaining": round(
                    self._cfg["daily_loss_limit"] - abs(min(self._daily_pnl, 0)), 2
                ),
            }

    # ------------------------------------------------------------------
    # Trading gate
    # ------------------------------------------------------------------

    def is_trading_allowed(self) -> Tuple[bool, str]:
        """Check whether trading is currently permitted.

        Validates market hours and overall daily-loss breaker.

        Returns
        -------
        tuple[bool, str]
            ``(True, "")`` if trading is allowed.
        """
        now = datetime.now().time()

        if not (self._market_open <= now <= self._market_close):
            return False, (
                f"Outside market hours ({self._cfg['market_open']} – "
                f"{self._cfg['market_close']})"
            )

        if self._daily_pnl < 0 and abs(self._daily_pnl) >= self._cfg["daily_loss_limit"]:
            return False, (
                f"Daily loss limit breached – P&L ₹{self._daily_pnl:,.2f}"
            )

        dd = self._compute_drawdown_pct()
        if dd >= self._cfg["max_drawdown_pct"]:
            return False, (
                f"Max drawdown breached – {dd:.2f}% "
                f"(limit {self._cfg['max_drawdown_pct']:.2f}%)"
            )

        return True, ""

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    def reset_daily_limits(self) -> None:
        """Reset all daily counters.  Call at the start of each trading day."""
        with self._lock:
            prev_pnl = self._daily_pnl
            self._daily_pnl = 0.0
            self._total_trades_today = 0
            self._winning_trades = 0
            self._losing_trades = 0
            self._open_positions = 0
            logger.info(
                "Daily limits reset – previous day P&L was ₹%.2f", prev_pnl
            )

    # ------------------------------------------------------------------
    # Trailing stop
    # ------------------------------------------------------------------

    def trailing_stop_update(
        self,
        position: Any,
        current_price: float,
    ) -> Optional[float]:
        """Compute a new trailing stop-loss if price has moved favourably.

        Parameters
        ----------
        position
            A ``Position`` dataclass (or duck-typed object) with ``side``,
            ``entry_price``, and ``stop_loss`` attributes.
        current_price : float
            Latest market price.

        Returns
        -------
        float or None
            The new stop-loss price, or ``None`` if no update is warranted.
        """
        trail_pct = self._cfg["trailing_stop_pct"]
        side = position.side.value if hasattr(position.side, "value") else str(position.side)

        if side.upper() == "BUY":
            # Move stop up when price rises
            new_stop = round(current_price * (1 - trail_pct / 100), 2)
            if new_stop > position.stop_loss and current_price > position.entry_price:
                logger.debug(
                    "Trailing stop updated (BUY) – old=%.2f  new=%.2f  "
                    "price=%.2f",
                    position.stop_loss, new_stop, current_price,
                )
                return new_stop
        else:
            # Move stop down when price falls
            new_stop = round(current_price * (1 + trail_pct / 100), 2)
            if new_stop < position.stop_loss and current_price < position.entry_price:
                logger.debug(
                    "Trailing stop updated (SELL) – old=%.2f  new=%.2f  "
                    "price=%.2f",
                    position.stop_loss, new_stop, current_price,
                )
                return new_stop

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_drawdown_pct(self) -> float:
        """Current drawdown as a percentage of peak capital."""
        if self._peak_capital <= 0:
            return 0.0
        return round(
            (self._peak_capital - self._current_capital) / self._peak_capital * 100,
            2,
        )
