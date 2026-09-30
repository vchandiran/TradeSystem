"""
strategy.ema_crossover
~~~~~~~~~~~~~~~~~~~~~~
EMA Crossover strategy with RSI and volume confirmation for the NSE
automated trading system.

Signal logic
------------
* **BUY** – Fast EMA crosses *above* Slow EMA, RSI is not overbought,
  and volume is above its rolling average.
* **SELL** – Fast EMA crosses *below* Slow EMA, RSI is not oversold,
  and volume is above its rolling average.

Exit logic
----------
* Stop-loss / target / trailing-stop hit.
* Reversal signal detected (crossover in opposite direction).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from core.models import OrderSide, Position, Signal, SignalType
from strategy.base_strategy import BaseStrategy


logger = logging.getLogger(__name__)


class EMACrossoverStrategy(BaseStrategy):
    """Dual-EMA crossover strategy with RSI + volume filters.

    Config keys
    -----------
    fast_ema_period : int
        Fast EMA look-back (default ``9``).
    slow_ema_period : int
        Slow EMA look-back (default ``21``).
    rsi_period : int
        RSI look-back (default ``14``).
    rsi_overbought : float
        RSI level above which BUY signals are suppressed (default ``70``).
    rsi_oversold : float
        RSI level below which SELL signals are suppressed (default ``30``).
    volume_avg_period : int
        Rolling window for average volume (default ``20``).
    volume_multiplier : float
        Minimum multiple of average volume required (default ``1.0``).
    trailing_stop_pct : float
        Trailing stop-loss percentage from peak price (default ``1.5``).
    min_data_points : int
        Minimum candles required before signal generation (default ``30``).
    """

    # Default configuration ------------------------------------------------

    _DEFAULTS: Dict[str, Any] = {
        "fast_ema_period": 9,
        "slow_ema_period": 21,
        "rsi_period": 14,
        "rsi_overbought": 70.0,
        "rsi_oversold": 30.0,
        "volume_avg_period": 20,
        "volume_multiplier": 1.0,
        "trailing_stop_pct": 1.5,
        "min_data_points": 30,
    }

    # Required OHLCV columns for internal DataFrames ----------------------

    _OHLCV_COLS = ["timestamp", "open", "high", "low", "close", "volume"]

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        merged = {**self._DEFAULTS, **config}
        super().__init__(name, merged)

        # Unpack for fast access
        self.fast_period: int = int(merged["fast_ema_period"])
        self.slow_period: int = int(merged["slow_ema_period"])
        self.rsi_period: int = int(merged["rsi_period"])
        self.rsi_overbought: float = float(merged["rsi_overbought"])
        self.rsi_oversold: float = float(merged["rsi_oversold"])
        self.volume_avg_period: int = int(merged["volume_avg_period"])
        self.volume_multiplier: float = float(merged["volume_multiplier"])
        self.trailing_stop_pct: float = float(merged["trailing_stop_pct"])
        self.min_data_points: int = int(merged["min_data_points"])

        # Per-symbol OHLCV history stored as DataFrames
        self._data: Dict[str, pd.DataFrame] = {}

        # Track peak prices for trailing stop per symbol
        self._peak_prices: Dict[str, float] = {}

        self.logger.info(
            "EMACrossover configured – fast=%d slow=%d rsi=%d "
            "rsi_ob=%.1f rsi_os=%.1f vol_avg=%d vol_mult=%.2f",
            self.fast_period,
            self.slow_period,
            self.rsi_period,
            self.rsi_overbought,
            self.rsi_oversold,
            self.volume_avg_period,
            self.volume_multiplier,
        )

    # ------------------------------------------------------------------
    # Data management
    # ------------------------------------------------------------------

    def update_data(self, symbol: str, candle_dict: Dict[str, Any]) -> None:
        """Append a single candle to the internal OHLCV DataFrame for *symbol*.

        Parameters
        ----------
        symbol : str
            NSE instrument symbol (e.g. ``"RELIANCE"``).
        candle_dict : dict
            Must contain keys: ``timestamp``, ``open``, ``high``, ``low``,
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

        ``market_data`` must include a ``"symbol"`` key.  All OHLCV data
        should have been fed via :meth:`update_data` beforehand.

        Parameters
        ----------
        market_data : dict
            Must contain ``"symbol"`` (str) and optionally ``"ltp"``
            (float) for the latest traded price.

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
            return self._generate_signal(symbol, df, market_data)
        except Exception:
            self.logger.exception(
                "Error generating signal for %s.", symbol
            )
            return None

    def should_exit(self, position: Any, market_data: dict) -> bool:
        """Check whether *position* should be closed.

        Checks (in priority order):
        1. Hard stop-loss hit.
        2. Target price hit.
        3. Trailing stop triggered.
        4. Reversal crossover detected.
        """
        try:
            return self._evaluate_exit(position, market_data)
        except Exception:
            self.logger.exception(
                "Error evaluating exit for %s.", getattr(position, "symbol", "?")
            )
            return False

    # ------------------------------------------------------------------
    # Signal generation (private)
    # ------------------------------------------------------------------

    def _generate_signal(
        self,
        symbol: str,
        df: pd.DataFrame,
        market_data: dict,
    ) -> Optional[Signal]:
        """Core signal logic – crossover + RSI + volume confirmation."""

        close = df["close"].astype(float).values
        volume = df["volume"].astype(float).values

        # --- Indicators ---------------------------------------------------
        fast_ema = self._calculate_ema(close, self.fast_period)
        slow_ema = self._calculate_ema(close, self.slow_period)
        rsi = self._calculate_rsi(close, self.rsi_period)
        vwap = self._calculate_vwap(df)

        if fast_ema is None or slow_ema is None or rsi is None:
            return None

        # Current & previous EMA values
        fast_now, fast_prev = fast_ema[-1], fast_ema[-2]
        slow_now, slow_prev = slow_ema[-1], slow_ema[-2]
        rsi_now = rsi[-1]

        # Volume confirmation
        avg_volume = np.mean(volume[-self.volume_avg_period:])
        current_volume = volume[-1]
        volume_confirmed = current_volume >= (avg_volume * self.volume_multiplier)

        # --- Crossover detection ------------------------------------------
        bullish_cross = fast_prev <= slow_prev and fast_now > slow_now
        bearish_cross = fast_prev >= slow_prev and fast_now < slow_now

        signal_type: Optional[SignalType] = None

        if bullish_cross and rsi_now < self.rsi_overbought and volume_confirmed:
            signal_type = SignalType.BUY
        elif bearish_cross and rsi_now > self.rsi_oversold and volume_confirmed:
            signal_type = SignalType.SELL

        if signal_type is None:
            return None

        # --- Signal strength ----------------------------------------------
        ema_spread = abs(fast_now - slow_now) / slow_now if slow_now else 0.0
        # Normalise spread to [0, 0.5] range → maps to strength contribution
        spread_strength = min(ema_spread / 0.02, 0.5)

        # RSI contribution: distance from neutral 50, mapped to [0, 0.3]
        rsi_strength = min(abs(rsi_now - 50.0) / 50.0, 0.3)

        # Volume contribution: how far above average, mapped to [0, 0.2]
        vol_ratio = (current_volume / avg_volume) if avg_volume > 0 else 1.0
        vol_strength = min((vol_ratio - 1.0) / 5.0, 0.2)

        strength = round(min(spread_strength + rsi_strength + vol_strength, 1.0), 4)

        price = float(close[-1])

        metadata: Dict[str, Any] = {
            "fast_ema": round(float(fast_now), 4),
            "slow_ema": round(float(slow_now), 4),
            "ema_spread": round(float(ema_spread), 6),
            "rsi": round(float(rsi_now), 2),
            "volume": int(current_volume),
            "avg_volume": round(float(avg_volume), 2),
            "volume_ratio": round(float(vol_ratio), 2),
            "vwap": round(float(vwap), 4) if vwap is not None else None,
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
            "%s signal for %s @ %.2f | strength=%.4f | RSI=%.2f | "
            "vol_ratio=%.2f | fast_ema=%.4f slow_ema=%.4f",
            signal_type.value,
            symbol,
            price,
            strength,
            rsi_now,
            vol_ratio,
            fast_now,
            slow_now,
        )
        return signal

    # ------------------------------------------------------------------
    # Exit evaluation (private)
    # ------------------------------------------------------------------

    def _evaluate_exit(self, position: Any, market_data: dict) -> bool:
        """Evaluate exit conditions against the current position."""

        symbol: str = position.symbol
        current_price: float = float(
            market_data.get("ltp", 0) or position.current_price
        )

        if current_price <= 0:
            self.logger.warning(
                "Cannot evaluate exit for %s – no valid current price.", symbol
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
                    "EXIT %s: trailing stop (price=%.2f peak=%.2f trail=%.2f).",
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

        # 4. Reversal signal (crossover in opposite direction) ------------
        df = self._data.get(symbol)
        if df is not None and len(df) >= self.min_data_points:
            close = df["close"].astype(float).values
            fast_ema = self._calculate_ema(close, self.fast_period)
            slow_ema = self._calculate_ema(close, self.slow_period)

            if fast_ema is not None and slow_ema is not None:
                fast_now, fast_prev = fast_ema[-1], fast_ema[-2]
                slow_now, slow_prev = slow_ema[-1], slow_ema[-2]

                bearish_cross = fast_prev >= slow_prev and fast_now < slow_now
                bullish_cross = fast_prev <= slow_prev and fast_now > slow_now

                if is_long and bearish_cross:
                    self.logger.info(
                        "EXIT %s: bearish EMA reversal detected.", symbol
                    )
                    return True
                if not is_long and bullish_cross:
                    self.logger.info(
                        "EXIT %s: bullish EMA reversal detected.", symbol
                    )
                    return True

        return False

    # ------------------------------------------------------------------
    # Technical indicator calculations
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_ema(
        data: np.ndarray, period: int
    ) -> Optional[np.ndarray]:
        """Calculate Exponential Moving Average.

        Parameters
        ----------
        data : np.ndarray
            1-D array of price values.
        period : int
            Look-back period.

        Returns
        -------
        np.ndarray or None
            EMA array of same length as *data*, or ``None`` if there is
            insufficient data.
        """
        if len(data) < period:
            return None

        multiplier = 2.0 / (period + 1)
        ema = np.empty_like(data, dtype=np.float64)

        # Seed with SMA over the first *period* values
        ema[:period] = np.nan
        ema[period - 1] = np.mean(data[:period])

        for i in range(period, len(data)):
            ema[i] = (data[i] - ema[i - 1]) * multiplier + ema[i - 1]

        return ema

    @staticmethod
    def _calculate_rsi(
        data: np.ndarray, period: int = 14
    ) -> Optional[np.ndarray]:
        """Calculate Relative Strength Index (Wilder smoothing).

        Parameters
        ----------
        data : np.ndarray
            1-D array of closing prices.
        period : int
            RSI look-back (default ``14``).

        Returns
        -------
        np.ndarray or None
            RSI array of same length as *data*, or ``None`` if there is
            insufficient data.
        """
        if len(data) < period + 1:
            return None

        deltas = np.diff(data)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        rsi = np.full(len(data), np.nan, dtype=np.float64)

        # Seed averages using simple mean of first *period* changes
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        if avg_loss == 0:
            rsi[period] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[period] = 100.0 - (100.0 / (1.0 + rs))

        # Wilder smoothing for remaining values
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

            if avg_loss == 0:
                rsi[i + 1] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))

        return rsi

    @staticmethod
    def _calculate_vwap(df: pd.DataFrame) -> Optional[float]:
        """Calculate Volume Weighted Average Price for the session.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain ``high``, ``low``, ``close``, and ``volume``
            columns.

        Returns
        -------
        float or None
            Current VWAP value, or ``None`` if calculation fails.
        """
        try:
            high = df["high"].astype(float).values
            low = df["low"].astype(float).values
            close = df["close"].astype(float).values
            volume = df["volume"].astype(float).values

            typical_price = (high + low + close) / 3.0
            cum_tp_vol = np.cumsum(typical_price * volume)
            cum_vol = np.cumsum(volume)

            if cum_vol[-1] == 0:
                return None

            return float(cum_tp_vol[-1] / cum_vol[-1])
        except Exception:
            return None
