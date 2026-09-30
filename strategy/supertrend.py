"""
strategy.supertrend
~~~~~~~~~~~~~~~~~~~
SuperTrend strategy for the NSE automated trading system.

The SuperTrend indicator uses ATR (Average True Range) to define dynamic
support / resistance bands.  A trend reversal is signalled when price
crosses above or below the SuperTrend line.

Signal logic
------------
* **BUY**  – price closes above the SuperTrend line (trend flips UP).
* **SELL** – price closes below the SuperTrend line (trend flips DOWN).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from core.models import OrderSide, Signal, SignalType
from strategy.base_strategy import BaseStrategy


logger = logging.getLogger(__name__)


class SuperTrendStrategy(BaseStrategy):
    """ATR-based SuperTrend crossover strategy.

    Config keys
    -----------
    period : int
        ATR look-back period (default ``10``).
    multiplier : float
        ATR multiplier for band width (default ``3.0``).
    min_data_points : int
        Minimum candles before signal generation (default ``20``).
    trailing_stop_pct : float
        Trailing stop-loss percentage from peak price (default ``2.0``).
    """

    _DEFAULTS: Dict[str, Any] = {
        "period": 10,
        "multiplier": 3.0,
        "min_data_points": 20,
        "trailing_stop_pct": 2.0,
    }

    _OHLCV_COLS = ["timestamp", "open", "high", "low", "close", "volume"]

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        merged = {**self._DEFAULTS, **config}
        super().__init__(name, merged)

        self.period: int = int(merged["period"])
        self.multiplier: float = float(merged["multiplier"])
        self.min_data_points: int = int(merged["min_data_points"])
        self.trailing_stop_pct: float = float(merged["trailing_stop_pct"])

        # Per-symbol OHLCV history
        self._data: Dict[str, pd.DataFrame] = {}

        # Per-symbol trend tracking:  1 = UP / -1 = DOWN / 0 = undefined
        self._trend: Dict[str, int] = {}

        # Per-symbol peak prices for trailing stop
        self._peak_prices: Dict[str, float] = {}

        self.logger.info(
            "SuperTrend configured – period=%d multiplier=%.2f",
            self.period,
            self.multiplier,
        )

    # ------------------------------------------------------------------
    # Data management
    # ------------------------------------------------------------------

    def update_data(self, symbol: str, candle_dict: Dict[str, Any]) -> None:
        """Append a single candle to the internal OHLCV store for *symbol*.

        Parameters
        ----------
        symbol : str
            NSE instrument symbol.
        candle_dict : dict
            Must contain: ``timestamp``, ``open``, ``high``, ``low``,
            ``close``, ``volume``.
        """
        missing = [c for c in self._OHLCV_COLS if c not in candle_dict]
        if missing:
            self.logger.error(
                "Candle for %s missing columns: %s – skipped.", symbol, missing
            )
            return

        row = {col: candle_dict[col] for col in self._OHLCV_COLS}
        new_row = pd.DataFrame([row])

        if symbol not in self._data:
            self._data[symbol] = new_row
        else:
            self._data[symbol] = pd.concat(
                [self._data[symbol], new_row], ignore_index=True
            )

        self.logger.debug(
            "Updated %s data – total candles: %d",
            symbol,
            len(self._data[symbol]),
        )

    # ------------------------------------------------------------------
    # Core strategy interface
    # ------------------------------------------------------------------

    def analyze(self, market_data: dict) -> Optional[Signal]:  # type: ignore[override]
        """Analyse the latest data for a symbol and return a signal.

        Parameters
        ----------
        market_data : dict
            Must contain ``"symbol"`` (str).

        Returns
        -------
        Signal or None
        """
        symbol: str = market_data.get("symbol", "")
        if not symbol:
            self.logger.warning("analyze() called without a symbol key.")
            return None

        df = self._data.get(symbol)
        if df is None or len(df) < self.min_data_points:
            self.logger.debug(
                "%s: insufficient data (%d/%d candles).",
                symbol,
                0 if df is None else len(df),
                self.min_data_points,
            )
            return None

        try:
            return self._generate_signal(symbol, df)
        except Exception:
            self.logger.exception(
                "Error generating SuperTrend signal for %s.", symbol
            )
            return None

    def should_exit(self, position: Any, market_data: dict) -> bool:
        """Determine whether *position* should be closed.

        Checks:
        1. Hard stop-loss hit.
        2. Target price hit.
        3. Trailing stop triggered.
        4. SuperTrend reversal (trend flips against the position).
        """
        try:
            return self._evaluate_exit(position, market_data)
        except Exception:
            self.logger.exception(
                "Error evaluating exit for %s.",
                getattr(position, "symbol", "?"),
            )
            return False

    # ------------------------------------------------------------------
    # SuperTrend calculation
    # ------------------------------------------------------------------

    def _calculate_atr(self, df: pd.DataFrame, period: int) -> np.ndarray:
        """Calculate Average True Range (ATR).

        Uses Wilder smoothing (exponential with ``alpha = 1/period``).

        Parameters
        ----------
        df : pd.DataFrame
            Must contain ``high``, ``low``, ``close`` columns.
        period : int
            ATR look-back.

        Returns
        -------
        np.ndarray
            ATR values; early entries will be ``NaN``.
        """
        high = df["high"].astype(float).values
        low = df["low"].astype(float).values
        close = df["close"].astype(float).values

        n = len(high)
        tr = np.empty(n, dtype=np.float64)
        tr[0] = high[0] - low[0]

        for i in range(1, n):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i - 1])
            lc = abs(low[i] - close[i - 1])
            tr[i] = max(hl, hc, lc)

        atr = np.full(n, np.nan, dtype=np.float64)

        if n < period:
            return atr

        # Seed with simple average
        atr[period - 1] = np.mean(tr[:period])

        # Wilder smoothing
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        return atr

    def _calculate_supertrend(
        self, df: pd.DataFrame
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute the SuperTrend line and direction array.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV DataFrame.

        Returns
        -------
        supertrend : np.ndarray
            The SuperTrend line values.
        direction : np.ndarray of int
            ``1`` for UP-trend, ``-1`` for DOWN-trend.
        """
        high = df["high"].astype(float).values
        low = df["low"].astype(float).values
        close = df["close"].astype(float).values
        n = len(close)

        atr = self._calculate_atr(df, self.period)
        hl2 = (high + low) / 2.0

        # Raw bands
        upper_band = hl2 + self.multiplier * atr
        lower_band = hl2 - self.multiplier * atr

        # Final bands (carry forward logic)
        final_upper = np.copy(upper_band)
        final_lower = np.copy(lower_band)

        supertrend = np.empty(n, dtype=np.float64)
        direction = np.zeros(n, dtype=np.int64)

        # Initialise – start of valid ATR window
        start = self.period - 1
        supertrend[:start] = np.nan
        direction[:start] = 0

        # Seed the first valid bar
        supertrend[start] = upper_band[start]
        direction[start] = -1  # assume down-trend initially

        for i in range(start + 1, n):
            # Final lower band: can only increase
            if final_lower[i] < final_lower[i - 1] and close[i - 1] > final_lower[i - 1]:
                final_lower[i] = final_lower[i - 1]

            # Final upper band: can only decrease
            if final_upper[i] > final_upper[i - 1] and close[i - 1] < final_upper[i - 1]:
                final_upper[i] = final_upper[i - 1]

            # Determine direction
            if direction[i - 1] == -1:  # was down-trend
                if close[i] > final_upper[i - 1]:
                    direction[i] = 1  # flip to up-trend
                else:
                    direction[i] = -1
            else:  # was up-trend
                if close[i] < final_lower[i - 1]:
                    direction[i] = -1  # flip to down-trend
                else:
                    direction[i] = 1

            # Set SuperTrend value
            if direction[i] == 1:
                supertrend[i] = final_lower[i]
            else:
                supertrend[i] = final_upper[i]

        return supertrend, direction

    # ------------------------------------------------------------------
    # Signal generation (private)
    # ------------------------------------------------------------------

    def _generate_signal(
        self,
        symbol: str,
        df: pd.DataFrame,
    ) -> Optional[Signal]:
        """Generate BUY/SELL signal based on SuperTrend crossover."""

        supertrend, direction = self._calculate_supertrend(df)

        # Need at least two valid data points to detect a flip
        if len(direction) < 2:
            return None

        curr_dir = int(direction[-1])
        prev_dir = int(direction[-2])
        prev_trend = self._trend.get(symbol, 0)

        # Update stored trend
        self._trend[symbol] = curr_dir

        # Detect direction *flip* at the latest bar
        if prev_dir == curr_dir:
            # No flip on this bar – but check first-time trend assignment
            if prev_trend == curr_dir:
                return None  # no change

        flip_to_up = prev_dir == -1 and curr_dir == 1
        flip_to_down = prev_dir == 1 and curr_dir == -1

        signal_type: Optional[SignalType] = None
        if flip_to_up:
            signal_type = SignalType.BUY
        elif flip_to_down:
            signal_type = SignalType.SELL
        else:
            return None

        close = df["close"].astype(float).values
        price = float(close[-1])
        atr = self._calculate_atr(df, self.period)
        atr_now = float(atr[-1]) if not np.isnan(atr[-1]) else 0.0
        st_now = float(supertrend[-1])

        # Signal strength: distance from SuperTrend line normalised by price
        distance = abs(price - st_now)
        distance_pct = (distance / price) if price > 0 else 0.0
        strength = round(min(distance_pct / 0.03, 1.0), 4)

        metadata: Dict[str, Any] = {
            "supertrend": round(st_now, 4),
            "atr": round(atr_now, 4),
            "direction": curr_dir,
            "prev_direction": prev_dir,
            "distance_from_st": round(distance, 4),
            "distance_pct": round(distance_pct, 6),
        }

        signal = Signal(
            symbol=symbol,
            signal_type=signal_type,
            price=price,
            timestamp=datetime.now(),
            strategy_name=self.name,
            strength=strength,
            metadata=metadata,
        )

        if not self.validate_signal(signal):
            return None

        self.logger.info(
            "%s signal for %s @ %.2f | ST=%.2f ATR=%.2f dir=%d | "
            "strength=%.4f",
            signal_type.value,
            symbol,
            price,
            st_now,
            atr_now,
            curr_dir,
            strength,
        )
        return signal

    # ------------------------------------------------------------------
    # Exit evaluation (private)
    # ------------------------------------------------------------------

    def _evaluate_exit(self, position: Any, market_data: dict) -> bool:
        """Evaluate exit conditions for the given position."""

        symbol: str = position.symbol
        current_price: float = float(
            market_data.get("ltp", 0) or position.current_price
        )

        if current_price <= 0:
            self.logger.warning(
                "Cannot evaluate exit for %s – no valid current price.",
                symbol,
            )
            return False

        is_long = position.side == OrderSide.BUY

        # 1. Hard stop-loss -----------------------------------------------
        if position.stop_loss > 0:
            if is_long and current_price <= position.stop_loss:
                self.logger.info(
                    "EXIT %s: stop-loss hit (%.2f <= %.2f).",
                    symbol,
                    current_price,
                    position.stop_loss,
                )
                return True
            if not is_long and current_price >= position.stop_loss:
                self.logger.info(
                    "EXIT %s: short stop-loss hit (%.2f >= %.2f).",
                    symbol,
                    current_price,
                    position.stop_loss,
                )
                return True

        # 2. Target price -------------------------------------------------
        if position.target > 0:
            if is_long and current_price >= position.target:
                self.logger.info(
                    "EXIT %s: target hit (%.2f >= %.2f).",
                    symbol,
                    current_price,
                    position.target,
                )
                return True
            if not is_long and current_price <= position.target:
                self.logger.info(
                    "EXIT %s: short target hit (%.2f <= %.2f).",
                    symbol,
                    current_price,
                    position.target,
                )
                return True

        # 3. Trailing stop ------------------------------------------------
        if self.trailing_stop_pct > 0:
            peak = self._peak_prices.get(symbol, current_price)
            if is_long:
                peak = max(peak, current_price)
            else:
                peak = min(peak, current_price)
            self._peak_prices[symbol] = peak

            trail_distance = peak * (self.trailing_stop_pct / 100.0)
            if is_long and current_price <= (peak - trail_distance):
                self.logger.info(
                    "EXIT %s: trailing stop (price=%.2f peak=%.2f "
                    "trail=%.2f).",
                    symbol,
                    current_price,
                    peak,
                    trail_distance,
                )
                return True
            if not is_long and current_price >= (peak + trail_distance):
                self.logger.info(
                    "EXIT %s: short trailing stop (price=%.2f peak=%.2f "
                    "trail=%.2f).",
                    symbol,
                    current_price,
                    peak,
                    trail_distance,
                )
                return True

        # 4. SuperTrend reversal ------------------------------------------
        trend = self._trend.get(symbol, 0)
        if is_long and trend == -1:
            self.logger.info(
                "EXIT %s: SuperTrend flipped DOWN against long position.",
                symbol,
            )
            return True
        if not is_long and trend == 1:
            self.logger.info(
                "EXIT %s: SuperTrend flipped UP against short position.",
                symbol,
            )
            return True

        return False
