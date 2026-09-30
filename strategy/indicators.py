"""
strategy.indicators
~~~~~~~~~~~~~~~~~~~
Comprehensive technical indicator library for the NSE trading system.
All functions operate on numpy arrays or pandas Series for performance.

Indicator Categories
--------------------
- **Trend**: EMA, SMA, MACD, ADX, SuperTrend, Ichimoku
- **Momentum**: RSI, Stochastic, Williams %R, CCI
- **Volatility**: Bollinger Bands, ATR
- **Volume**: VWAP, OBV, Volume Profile
- **Candlestick Patterns**: Engulfing, Hammer, Doji, Morning/Evening Star
- **Support/Resistance**: Pivot Points, Support/Resistance Levels
- **Composite**: Trend Strength (ADX + slope + EMA alignment)

Usage
-----
>>> from strategy.indicators import ema, rsi, macd
>>> ema_values = ema(close_prices, period=20)
>>> rsi_values = rsi(close_prices, period=14)
>>> macd_line, signal_line, histogram = macd(close_prices)
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_numpy(data: np.ndarray | pd.Series) -> np.ndarray:
    """Convert input to a float64 numpy array, handling pandas Series."""
    if isinstance(data, pd.Series):
        return data.to_numpy(dtype=np.float64, na_value=np.nan)
    return np.asarray(data, dtype=np.float64)


def _validate_period(length: int, period: int, name: str) -> bool:
    """Return True if the array has enough data for the given period.

    Logs a warning and returns False when data is insufficient, allowing
    callers to return a NaN-filled array immediately.
    """
    if length < period:
        logger.warning(
            "%s: insufficient data – need %d bars, got %d", name, period, length
        )
        return False
    return True


def _nan_array(length: int) -> np.ndarray:
    """Return a float64 array of *length* filled with NaN."""
    return np.full(length, np.nan, dtype=np.float64)


# ===================================================================
# 1. Simple Moving Average
# ===================================================================

def sma(data: np.ndarray | pd.Series, period: int) -> np.ndarray:
    """Simple Moving Average.

    Parameters
    ----------
    data : array-like
        Price series (typically close prices).
    period : int
        Look-back window length.

    Returns
    -------
    np.ndarray
        SMA values; first ``period - 1`` elements are NaN.
    """
    arr = _to_numpy(data)
    n = len(arr)
    if not _validate_period(n, period, "SMA"):
        return _nan_array(n)

    # Cumulative-sum trick for O(n) computation
    out = _nan_array(n)
    cumsum = np.cumsum(arr)
    out[period - 1:] = (cumsum[period - 1:] - np.concatenate(([0.0], cumsum[:-period]))) / period
    return out


# ===================================================================
# 2. Exponential Moving Average
# ===================================================================

def ema(data: np.ndarray | pd.Series, period: int) -> np.ndarray:
    """Exponential Moving Average, seeded with the SMA of the first *period* values.

    Parameters
    ----------
    data : array-like
        Price series.
    period : int
        Smoothing window.

    Returns
    -------
    np.ndarray
        EMA values; first ``period - 1`` elements are NaN.
    """
    arr = _to_numpy(data)
    n = len(arr)
    if not _validate_period(n, period, "EMA"):
        return _nan_array(n)

    out = _nan_array(n)
    alpha = 2.0 / (period + 1)

    # Seed with SMA
    out[period - 1] = np.mean(arr[:period])

    # Recursive EMA – unavoidable loop due to data dependency
    for i in range(period, n):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]

    return out


# ===================================================================
# 3. RSI (Wilder Smoothing)
# ===================================================================

def rsi(data: np.ndarray | pd.Series, period: int = 14) -> np.ndarray:
    """Relative Strength Index using Wilder's smoothing method.

    Parameters
    ----------
    data : array-like
        Price series (typically close prices).
    period : int, default 14
        Look-back period.

    Returns
    -------
    np.ndarray
        RSI values in [0, 100]; first ``period`` elements are NaN.
    """
    arr = _to_numpy(data)
    n = len(arr)
    if not _validate_period(n, period + 1, "RSI"):
        return _nan_array(n)

    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    out = _nan_array(n)

    # Seed averages with simple mean of the first *period* changes
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0.0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - 100.0 / (1.0 + rs)

    # Wilder smoothing
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0.0:
            out[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i + 1] = 100.0 - 100.0 / (1.0 + rs)

    return out


# ===================================================================
# 4. MACD
# ===================================================================

def macd(
    data: np.ndarray | pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Moving Average Convergence Divergence.

    Parameters
    ----------
    data : array-like
        Price series.
    fast : int, default 12
        Fast EMA period.
    slow : int, default 26
        Slow EMA period.
    signal : int, default 9
        Signal-line EMA period.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray]
        ``(macd_line, signal_line, histogram)``
    """
    arr = _to_numpy(data)
    n = len(arr)
    if not _validate_period(n, slow + signal, "MACD"):
        return _nan_array(n), _nan_array(n), _nan_array(n)

    fast_ema = ema(arr, fast)
    slow_ema = ema(arr, slow)
    macd_line = fast_ema - slow_ema

    # Signal line is the EMA of the MACD line (ignoring leading NaNs)
    signal_line = _nan_array(n)
    # Find the first non-NaN index of macd_line
    first_valid = slow - 1  # slow EMA starts here
    valid_macd = macd_line[first_valid:]
    signal_ema = ema(valid_macd, signal)

    signal_line[first_valid:] = signal_ema
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


# ===================================================================
# 5. Bollinger Bands
# ===================================================================

def bollinger_bands(
    data: np.ndarray | pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands.

    Parameters
    ----------
    data : array-like
        Price series.
    period : int, default 20
        SMA / standard-deviation window.
    std_dev : float, default 2.0
        Number of standard deviations for the bands.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray]
        ``(upper_band, middle_band, lower_band)``
    """
    arr = _to_numpy(data)
    n = len(arr)
    if not _validate_period(n, period, "Bollinger Bands"):
        return _nan_array(n), _nan_array(n), _nan_array(n)

    middle = sma(arr, period)

    # Rolling standard deviation via cumsum of squares
    rolling_std = _nan_array(n)
    for i in range(period - 1, n):
        window = arr[i - period + 1 : i + 1]
        rolling_std[i] = np.std(window, ddof=0)

    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std

    return upper, middle, lower


# ===================================================================
# 6. ATR (Average True Range)
# ===================================================================

def atr(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    period: int = 14,
) -> np.ndarray:
    """Average True Range using Wilder's smoothing.

    Parameters
    ----------
    high, low, close : array-like
        OHLC components.
    period : int, default 14
        Look-back period.

    Returns
    -------
    np.ndarray
        ATR values; first ``period`` elements are NaN.
    """
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    n = len(c)
    if not _validate_period(n, period + 1, "ATR"):
        return _nan_array(n)

    # True Range
    tr = _nan_array(n)
    tr[0] = h[0] - l[0]
    prev_close = c[:-1]
    tr[1:] = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - prev_close), np.abs(l[1:] - prev_close)),
    )

    # Wilder smoothing
    out = _nan_array(n)
    out[period] = np.mean(tr[1 : period + 1])
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period

    return out


# ===================================================================
# 7. ADX (Average Directional Index)
# ===================================================================

def adx(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    period: int = 14,
) -> np.ndarray:
    """Average Directional Index – measures trend strength (0-100).

    Parameters
    ----------
    high, low, close : array-like
        OHLC components.
    period : int, default 14
        Look-back period.

    Returns
    -------
    np.ndarray
        ADX values; early elements are NaN until enough data is available.
    """
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    n = len(c)
    if not _validate_period(n, 2 * period + 1, "ADX"):
        return _nan_array(n)

    # True Range & directional movements
    tr = np.empty(n, dtype=np.float64)
    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)

    tr[0] = h[0] - l[0]
    for i in range(1, n):
        hl = h[i] - l[i]
        hpc = abs(h[i] - c[i - 1])
        lpc = abs(l[i] - c[i - 1])
        tr[i] = max(hl, hpc, lpc)

        up_move = h[i] - h[i - 1]
        down_move = l[i - 1] - l[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # Wilder-smooth TR, +DM, -DM
    smoothed_tr = _nan_array(n)
    smoothed_plus = _nan_array(n)
    smoothed_minus = _nan_array(n)

    smoothed_tr[period] = np.sum(tr[1 : period + 1])
    smoothed_plus[period] = np.sum(plus_dm[1 : period + 1])
    smoothed_minus[period] = np.sum(minus_dm[1 : period + 1])

    for i in range(period + 1, n):
        smoothed_tr[i] = smoothed_tr[i - 1] - smoothed_tr[i - 1] / period + tr[i]
        smoothed_plus[i] = smoothed_plus[i - 1] - smoothed_plus[i - 1] / period + plus_dm[i]
        smoothed_minus[i] = smoothed_minus[i - 1] - smoothed_minus[i - 1] / period + minus_dm[i]

    # +DI / -DI
    plus_di = _nan_array(n)
    minus_di = _nan_array(n)
    dx = _nan_array(n)

    for i in range(period, n):
        if smoothed_tr[i] != 0:
            plus_di[i] = 100.0 * smoothed_plus[i] / smoothed_tr[i]
            minus_di[i] = 100.0 * smoothed_minus[i] / smoothed_tr[i]
        else:
            plus_di[i] = 0.0
            minus_di[i] = 0.0

        di_sum = plus_di[i] + minus_di[i]
        dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum if di_sum != 0 else 0.0

    # ADX = Wilder-smoothed DX
    out = _nan_array(n)
    adx_start = 2 * period
    if adx_start < n:
        out[adx_start] = np.nanmean(dx[period : adx_start + 1])
        for i in range(adx_start + 1, n):
            out[i] = (out[i - 1] * (period - 1) + dx[i]) / period

    return out


# ===================================================================
# 8. SuperTrend
# ===================================================================

def supertrend(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    period: int = 10,
    multiplier: float = 3.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """SuperTrend indicator.

    Parameters
    ----------
    high, low, close : array-like
        OHLC components.
    period : int, default 10
        ATR period.
    multiplier : float, default 3.0
        ATR multiplier for the bands.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(supertrend_values, direction)`` where direction is
        +1 (uptrend / bullish) or -1 (downtrend / bearish).
    """
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    n = len(c)
    if not _validate_period(n, period + 2, "SuperTrend"):
        return _nan_array(n), _nan_array(n)

    atr_vals = atr(h, l, c, period)
    hl2 = (h + l) / 2.0

    upper_band = hl2 + multiplier * atr_vals
    lower_band = hl2 - multiplier * atr_vals

    st = _nan_array(n)
    direction = _nan_array(n)

    # Find first valid index (where ATR becomes available)
    first_valid = period
    while first_valid < n and np.isnan(atr_vals[first_valid]):
        first_valid += 1
    if first_valid >= n:
        return _nan_array(n), _nan_array(n)

    st[first_valid] = upper_band[first_valid]
    direction[first_valid] = -1.0  # start bearish

    for i in range(first_valid + 1, n):
        if np.isnan(upper_band[i]) or np.isnan(lower_band[i]):
            continue

        # Carry forward upper/lower bands with clamping logic
        if upper_band[i] < upper_band[i - 1] or c[i - 1] > upper_band[i - 1]:
            pass  # use current upper_band[i]
        else:
            upper_band[i] = upper_band[i - 1]

        if lower_band[i] > lower_band[i - 1] or c[i - 1] < lower_band[i - 1]:
            pass  # use current lower_band[i]
        else:
            lower_band[i] = lower_band[i - 1]

        # Determine direction
        if direction[i - 1] == -1.0:
            # Was bearish
            if c[i] > upper_band[i]:
                direction[i] = 1.0
                st[i] = lower_band[i]
            else:
                direction[i] = -1.0
                st[i] = upper_band[i]
        else:
            # Was bullish
            if c[i] < lower_band[i]:
                direction[i] = -1.0
                st[i] = upper_band[i]
            else:
                direction[i] = 1.0
                st[i] = lower_band[i]

    return st, direction


# ===================================================================
# 9. VWAP (Cumulative)
# ===================================================================

def vwap(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    volume: np.ndarray | pd.Series,
) -> np.ndarray:
    """Cumulative Volume-Weighted Average Price.

    Typically reset each trading session; the caller is responsible for
    providing a single session's data when intraday reset is desired.

    Parameters
    ----------
    high, low, close : array-like
        OHLC components.
    volume : array-like
        Trade volume per bar.

    Returns
    -------
    np.ndarray
        Cumulative VWAP.
    """
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    v = _to_numpy(volume)
    n = len(c)

    typical_price = (h + l + c) / 3.0
    cum_tp_vol = np.cumsum(typical_price * v)
    cum_vol = np.cumsum(v)

    out = _nan_array(n)
    mask = cum_vol != 0
    out[mask] = cum_tp_vol[mask] / cum_vol[mask]
    return out


# ===================================================================
# 10. Stochastic Oscillator
# ===================================================================

def stochastic(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> Tuple[np.ndarray, np.ndarray]:
    """Stochastic Oscillator (%K and %D).

    Parameters
    ----------
    high, low, close : array-like
        OHLC components.
    k_period : int, default 14
        Look-back for %K.
    d_period : int, default 3
        SMA smoothing period for %D.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(%K, %D)`` in [0, 100].
    """
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    n = len(c)
    if not _validate_period(n, k_period, "Stochastic"):
        return _nan_array(n), _nan_array(n)

    k = _nan_array(n)
    for i in range(k_period - 1, n):
        window_h = h[i - k_period + 1 : i + 1]
        window_l = l[i - k_period + 1 : i + 1]
        highest = np.max(window_h)
        lowest = np.min(window_l)
        hl_range = highest - lowest
        k[i] = 100.0 * (c[i] - lowest) / hl_range if hl_range != 0 else 50.0

    d = sma(k, d_period)
    return k, d


# ===================================================================
# 11. Pivot Points (Standard / Floor)
# ===================================================================

def pivot_points(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
) -> Dict[str, float]:
    """Standard (Floor Trader) Pivot Points from the prior session.

    Pass in a single bar's high/low/close (e.g. previous day) or arrays
    whose last element represents the prior session.

    Parameters
    ----------
    high, low, close : float or array-like
        If array, the **last** element is used.

    Returns
    -------
    dict[str, float]
        Keys: ``PP``, ``R1``, ``R2``, ``R3``, ``S1``, ``S2``, ``S3``.
    """
    h_val = float(_to_numpy(np.atleast_1d(high))[-1])
    l_val = float(_to_numpy(np.atleast_1d(low))[-1])
    c_val = float(_to_numpy(np.atleast_1d(close))[-1])

    pp = (h_val + l_val + c_val) / 3.0
    r1 = 2.0 * pp - l_val
    s1 = 2.0 * pp - h_val
    r2 = pp + (h_val - l_val)
    s2 = pp - (h_val - l_val)
    r3 = h_val + 2.0 * (pp - l_val)
    s3 = l_val - 2.0 * (h_val - pp)

    return {"PP": pp, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3}


# ===================================================================
# 12. OBV (On-Balance Volume)
# ===================================================================

def obv(
    close: np.ndarray | pd.Series,
    volume: np.ndarray | pd.Series,
) -> np.ndarray:
    """On-Balance Volume.

    Parameters
    ----------
    close : array-like
        Close prices.
    volume : array-like
        Trade volume per bar.

    Returns
    -------
    np.ndarray
        Cumulative OBV.
    """
    c = _to_numpy(close)
    v = _to_numpy(volume)
    n = len(c)

    direction = np.zeros(n, dtype=np.float64)
    direction[1:] = np.sign(np.diff(c))

    return np.cumsum(direction * v)


# ===================================================================
# 13. CCI (Commodity Channel Index)
# ===================================================================

def cci(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    period: int = 20,
) -> np.ndarray:
    """Commodity Channel Index.

    Parameters
    ----------
    high, low, close : array-like
        OHLC components.
    period : int, default 20
        Look-back period.

    Returns
    -------
    np.ndarray
        CCI values; first ``period - 1`` elements are NaN.
    """
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    n = len(c)
    if not _validate_period(n, period, "CCI"):
        return _nan_array(n)

    tp = (h + l + c) / 3.0
    tp_sma = sma(tp, period)

    # Mean absolute deviation
    mad = _nan_array(n)
    for i in range(period - 1, n):
        window = tp[i - period + 1 : i + 1]
        mad[i] = np.mean(np.abs(window - tp_sma[i]))

    out = _nan_array(n)
    nonzero = mad != 0
    valid = ~np.isnan(tp_sma) & ~np.isnan(mad) & nonzero
    out[valid] = (tp[valid] - tp_sma[valid]) / (0.015 * mad[valid])
    return out


# ===================================================================
# 14. Williams %R
# ===================================================================

def williams_r(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    period: int = 14,
) -> np.ndarray:
    """Williams %R oscillator.

    Parameters
    ----------
    high, low, close : array-like
        OHLC components.
    period : int, default 14
        Look-back period.

    Returns
    -------
    np.ndarray
        Values in [-100, 0]; first ``period - 1`` elements are NaN.
    """
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    n = len(c)
    if not _validate_period(n, period, "Williams %R"):
        return _nan_array(n)

    out = _nan_array(n)
    for i in range(period - 1, n):
        highest = np.max(h[i - period + 1 : i + 1])
        lowest = np.min(l[i - period + 1 : i + 1])
        hl_range = highest - lowest
        out[i] = -100.0 * (highest - c[i]) / hl_range if hl_range != 0 else 0.0

    return out


# ===================================================================
# 15. Ichimoku Cloud
# ===================================================================

def ichimoku(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
) -> Dict[str, np.ndarray]:
    """Ichimoku Kinko Hyo components.

    Parameters
    ----------
    high, low, close : array-like
        OHLC components.
    tenkan : int, default 9
        Tenkan-sen (conversion line) period.
    kijun : int, default 26
        Kijun-sen (base line) period.
    senkou_b : int, default 52
        Senkou Span B period.

    Returns
    -------
    dict[str, np.ndarray]
        Keys: ``tenkan_sen``, ``kijun_sen``, ``senkou_a``,
        ``senkou_b``, ``chikou``.  Senkou spans are shifted forward
        by *kijun* periods (padded with NaN); Chikou is shifted back
        by *kijun* periods.
    """
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    n = len(c)

    def _midline(src_h: np.ndarray, src_l: np.ndarray, period: int) -> np.ndarray:
        """Donchian-channel midline: (highest-high + lowest-low) / 2."""
        out = _nan_array(n)
        for i in range(period - 1, n):
            seg_h = src_h[i - period + 1 : i + 1]
            seg_l = src_l[i - period + 1 : i + 1]
            out[i] = (np.max(seg_h) + np.min(seg_l)) / 2.0
        return out

    tenkan_sen = _midline(h, l, tenkan)
    kijun_sen = _midline(h, l, kijun)

    # Senkou Span A = (Tenkan + Kijun) / 2, shifted forward kijun periods
    senkou_a_raw = (tenkan_sen + kijun_sen) / 2.0
    senkou_a = np.concatenate([_nan_array(kijun), senkou_a_raw])[:n]

    # Senkou Span B = midline(senkou_b_period), shifted forward kijun periods
    senkou_b_raw = _midline(h, l, senkou_b)
    senkou_b_out = np.concatenate([_nan_array(kijun), senkou_b_raw])[:n]

    # Chikou Span = close shifted back kijun periods
    chikou = np.concatenate([c[kijun:], _nan_array(kijun)])

    return {
        "tenkan_sen": tenkan_sen,
        "kijun_sen": kijun_sen,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b_out,
        "chikou": chikou,
    }


# ===================================================================
# 16. Heikin-Ashi
# ===================================================================

def heikin_ashi(
    open_arr: np.ndarray | pd.Series,
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Heikin-Ashi candles.

    Parameters
    ----------
    open_arr, high, low, close : array-like
        Standard OHLC bars.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
        ``(ha_open, ha_high, ha_low, ha_close)``
    """
    o = _to_numpy(open_arr)
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    n = len(c)

    ha_close = (o + h + l + c) / 4.0

    ha_open = np.empty(n, dtype=np.float64)
    ha_open[0] = (o[0] + c[0]) / 2.0
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0

    ha_high = np.maximum(h, np.maximum(ha_open, ha_close))
    ha_low = np.minimum(l, np.minimum(ha_open, ha_close))

    return ha_open, ha_high, ha_low, ha_close


# ===================================================================
# 17. Volume Profile
# ===================================================================

def volume_profile(
    close: np.ndarray | pd.Series,
    volume: np.ndarray | pd.Series,
    bins: int = 20,
) -> Dict[str, np.ndarray | float]:
    """Volume Profile / Market Profile.

    Parameters
    ----------
    close : array-like
        Close prices.
    volume : array-like
        Trade volume per bar.
    bins : int, default 20
        Number of price-level bins.

    Returns
    -------
    dict
        ``price_levels`` (bin centres), ``volumes`` (aggregated volume
        per bin), ``poc`` (Point of Control – price level with the
        highest volume).
    """
    c = _to_numpy(close)
    v = _to_numpy(volume)

    bin_edges = np.linspace(np.nanmin(c), np.nanmax(c), bins + 1)
    bin_indices = np.digitize(c, bin_edges) - 1
    bin_indices = np.clip(bin_indices, 0, bins - 1)

    volumes = np.zeros(bins, dtype=np.float64)
    np.add.at(volumes, bin_indices, v)

    price_levels = (bin_edges[:-1] + bin_edges[1:]) / 2.0
    poc_idx = int(np.argmax(volumes))

    return {
        "price_levels": price_levels,
        "volumes": volumes,
        "poc": float(price_levels[poc_idx]),
    }


# ===================================================================
# 18–19. Engulfing Patterns
# ===================================================================

def is_engulfing_bullish(
    open_arr: np.ndarray | pd.Series,
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
) -> np.ndarray:
    """Detect bullish engulfing candle patterns.

    A bullish engulfing occurs when a bearish candle is followed by a
    larger bullish candle whose body fully engulfs the prior candle's body.

    Returns
    -------
    np.ndarray[bool]
        Boolean array; True at bar indices where the pattern completes.
    """
    o = _to_numpy(open_arr)
    c = _to_numpy(close)
    n = len(c)

    result = np.zeros(n, dtype=bool)
    if n < 2:
        return result

    prev_bearish = c[:-1] < o[:-1]             # prior bar is bearish
    curr_bullish = c[1:] > o[1:]               # current bar is bullish
    engulfs_open = o[1:] <= c[:-1]             # current open ≤ prior close
    engulfs_close = c[1:] >= o[:-1]            # current close ≥ prior open

    result[1:] = prev_bearish & curr_bullish & engulfs_open & engulfs_close
    return result


def is_engulfing_bearish(
    open_arr: np.ndarray | pd.Series,
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
) -> np.ndarray:
    """Detect bearish engulfing candle patterns.

    A bearish engulfing occurs when a bullish candle is followed by a
    larger bearish candle whose body fully engulfs the prior candle's body.

    Returns
    -------
    np.ndarray[bool]
        Boolean array; True at bar indices where the pattern completes.
    """
    o = _to_numpy(open_arr)
    c = _to_numpy(close)
    n = len(c)

    result = np.zeros(n, dtype=bool)
    if n < 2:
        return result

    prev_bullish = c[:-1] > o[:-1]
    curr_bearish = c[1:] < o[1:]
    engulfs_open = o[1:] >= c[:-1]
    engulfs_close = c[1:] <= o[:-1]

    result[1:] = prev_bullish & curr_bearish & engulfs_open & engulfs_close
    return result


# ===================================================================
# 20. Hammer
# ===================================================================

def is_hammer(
    open_arr: np.ndarray | pd.Series,
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
) -> np.ndarray:
    """Detect hammer candle patterns (bullish reversal signal).

    Criteria:
    - Lower shadow ≥ 2× the real body.
    - Upper shadow ≤ 10 % of the bar range.
    - Real body is in the upper third of the bar range.

    Returns
    -------
    np.ndarray[bool]
    """
    o = _to_numpy(open_arr)
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)

    body = np.abs(c - o)
    bar_range = h - l

    # Avoid division by zero
    safe_range = np.where(bar_range == 0, np.nan, bar_range)
    safe_body = np.where(body == 0, 1e-10, body)

    upper_shadow = h - np.maximum(o, c)
    lower_shadow = np.minimum(o, c) - l

    long_lower = lower_shadow >= 2.0 * safe_body
    small_upper = upper_shadow <= 0.10 * safe_range
    body_in_upper = (np.minimum(o, c) - l) >= 0.6 * safe_range

    result = long_lower & small_upper & body_in_upper
    # Mask out where range was zero
    result = result & (bar_range > 0)
    return result.astype(bool)


# ===================================================================
# 21. Doji
# ===================================================================

def is_doji(
    open_arr: np.ndarray | pd.Series,
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    threshold: float = 0.1,
) -> np.ndarray:
    """Detect doji candle patterns (indecision signal).

    A doji has a very small real body relative to its total range.

    Parameters
    ----------
    threshold : float, default 0.1
        Maximum body-to-range ratio to qualify as a doji.

    Returns
    -------
    np.ndarray[bool]
    """
    o = _to_numpy(open_arr)
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)

    body = np.abs(c - o)
    bar_range = h - l

    safe_range = np.where(bar_range == 0, np.nan, bar_range)
    ratio = body / safe_range

    result = ratio <= threshold
    # Zero-range bars are not dojis
    result = np.where(bar_range == 0, False, result)
    return np.asarray(result, dtype=bool)


# ===================================================================
# 22. Morning Star
# ===================================================================

def is_morning_star(
    open_arr: np.ndarray | pd.Series,
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
) -> np.ndarray:
    """Detect morning star patterns (three-bar bullish reversal).

    Criteria:
    1. Bar 0: large bearish candle.
    2. Bar 1: small body (star) that gaps down from bar 0's close.
    3. Bar 2: large bullish candle that closes above the midpoint of bar 0.

    Returns
    -------
    np.ndarray[bool]
        True at the index of bar 2 (pattern completion bar).
    """
    o = _to_numpy(open_arr)
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    n = len(c)

    result = np.zeros(n, dtype=bool)
    if n < 3:
        return result

    body = np.abs(c - o)
    bar_range = h - l
    avg_body = sma(body, 10)

    for i in range(2, n):
        avg = avg_body[i] if not np.isnan(avg_body[i]) else np.mean(body[max(0, i - 10) : i + 1])
        if avg == 0:
            continue

        # Bar 0: large bearish
        bar0_bearish = c[i - 2] < o[i - 2] and body[i - 2] > avg
        # Bar 1: small body (star)
        bar1_small = body[i - 1] < 0.5 * avg
        # Bar 1 gaps down (its upper body is below bar 0's close)
        bar1_gap = max(o[i - 1], c[i - 1]) < c[i - 2]
        # Bar 2: large bullish, closes above midpoint of bar 0
        bar0_mid = (o[i - 2] + c[i - 2]) / 2.0
        bar2_bullish = c[i] > o[i] and body[i] > avg and c[i] > bar0_mid

        result[i] = bar0_bearish and bar1_small and bar1_gap and bar2_bullish

    return result


# ===================================================================
# 23. Evening Star
# ===================================================================

def is_evening_star(
    open_arr: np.ndarray | pd.Series,
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
) -> np.ndarray:
    """Detect evening star patterns (three-bar bearish reversal).

    Criteria:
    1. Bar 0: large bullish candle.
    2. Bar 1: small body (star) that gaps up from bar 0's close.
    3. Bar 2: large bearish candle that closes below the midpoint of bar 0.

    Returns
    -------
    np.ndarray[bool]
        True at the index of bar 2 (pattern completion bar).
    """
    o = _to_numpy(open_arr)
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    n = len(c)

    result = np.zeros(n, dtype=bool)
    if n < 3:
        return result

    body = np.abs(c - o)
    bar_range = h - l
    avg_body = sma(body, 10)

    for i in range(2, n):
        avg = avg_body[i] if not np.isnan(avg_body[i]) else np.mean(body[max(0, i - 10) : i + 1])
        if avg == 0:
            continue

        # Bar 0: large bullish
        bar0_bullish = c[i - 2] > o[i - 2] and body[i - 2] > avg
        # Bar 1: small body (star)
        bar1_small = body[i - 1] < 0.5 * avg
        # Bar 1 gaps up
        bar1_gap = min(o[i - 1], c[i - 1]) > c[i - 2]
        # Bar 2: large bearish, closes below midpoint of bar 0
        bar0_mid = (o[i - 2] + c[i - 2]) / 2.0
        bar2_bearish = c[i] < o[i] and body[i] > avg and c[i] < bar0_mid

        result[i] = bar0_bullish and bar1_small and bar1_gap and bar2_bearish

    return result


# ===================================================================
# 24. Support / Resistance Levels
# ===================================================================

def support_resistance_levels(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    lookback: int = 20,
) -> Tuple[List[float], List[float]]:
    """Identify support and resistance levels via rolling pivot extremes.

    The algorithm finds local minima (support) and local maxima (resistance)
    over rolling windows, then clusters nearby levels (within 0.5 % of each
    other) to avoid duplication.

    Parameters
    ----------
    high, low, close : array-like
        OHLC components.
    lookback : int, default 20
        Rolling window for detecting swing highs/lows.

    Returns
    -------
    tuple[list[float], list[float]]
        ``(support_levels, resistance_levels)`` sorted ascending.
    """
    h = _to_numpy(high)
    l = _to_numpy(low)
    c = _to_numpy(close)
    n = len(c)

    supports: List[float] = []
    resistances: List[float] = []

    half = lookback // 2
    if n < lookback:
        return supports, resistances

    # Detect swing highs and swing lows
    for i in range(half, n - half):
        window_h = h[i - half : i + half + 1]
        window_l = l[i - half : i + half + 1]

        if h[i] == np.max(window_h):
            resistances.append(float(h[i]))
        if l[i] == np.min(window_l):
            supports.append(float(l[i]))

    def _cluster(levels: List[float], tolerance: float = 0.005) -> List[float]:
        """Merge nearby levels into their mean."""
        if not levels:
            return []
        sorted_lvls = sorted(levels)
        clusters: List[List[float]] = [[sorted_lvls[0]]]
        for lvl in sorted_lvls[1:]:
            if abs(lvl - clusters[-1][-1]) / clusters[-1][-1] < tolerance:
                clusters[-1].append(lvl)
            else:
                clusters.append([lvl])
        return sorted([float(np.mean(cl)) for cl in clusters])

    return _cluster(supports), _cluster(resistances)


# ===================================================================
# 25. Trend Strength (Composite)
# ===================================================================

def trend_strength(
    close: np.ndarray | pd.Series,
    period: int = 20,
    high: Optional[np.ndarray | pd.Series] = None,
    low: Optional[np.ndarray | pd.Series] = None,
) -> np.ndarray:
    """Composite trend-strength score in [0, 100].

    Combines three components (equally weighted):
    1. **ADX** (normalised to 0-100) – directional movement strength.
    2. **Price slope** – linear-regression slope of close over *period*
       bars, normalised against ATR to be scale-independent.
    3. **EMA alignment** – degree to which short EMA > medium EMA > long
       EMA (or vice-versa for down-trends).

    When *high* / *low* are not provided, ATR and ADX are approximated
    from close alone (using ``close ± 0`` for high/low).

    Parameters
    ----------
    close : array-like
        Close prices.
    period : int, default 20
        Base period for sub-indicators.
    high, low : array-like, optional
        High / low prices.  If omitted, *close* is used as a proxy.

    Returns
    -------
    np.ndarray
        Trend-strength values in [0, 100]; early values are NaN.
    """
    c = _to_numpy(close)
    n = len(c)
    h = _to_numpy(high) if high is not None else c.copy()
    l = _to_numpy(low) if low is not None else c.copy()

    out = _nan_array(n)

    # --- Component 1: ADX (0–100) ---
    adx_period = max(period // 2, 7)
    adx_vals = adx(h, l, c, adx_period)

    # --- Component 2: Price slope normalised by ATR ---
    atr_vals = atr(h, l, c, adx_period)
    slope_score = _nan_array(n)
    x = np.arange(period, dtype=np.float64)
    x_mean = x.mean()
    x_var = np.sum((x - x_mean) ** 2)

    for i in range(period - 1, n):
        window = c[i - period + 1 : i + 1]
        y_mean = np.mean(window)
        slope = np.sum((x - x_mean) * (window - y_mean)) / x_var if x_var != 0 else 0.0
        # Normalise: slope per bar / ATR → dimensionless
        a = atr_vals[i] if not np.isnan(atr_vals[i]) else np.std(window)
        if a > 0:
            normalised = abs(slope) / a
        else:
            normalised = 0.0
        # Map to 0–100 using a sigmoid-like clamp (cap at ~3 ATR/bar)
        slope_score[i] = min(normalised / 0.03 * 100.0, 100.0)

    # --- Component 3: EMA alignment ---
    ema_short = ema(c, max(period // 4, 3))
    ema_mid = ema(c, max(period // 2, 5))
    ema_long = ema(c, period)

    alignment = _nan_array(n)
    for i in range(n):
        if np.isnan(ema_short[i]) or np.isnan(ema_mid[i]) or np.isnan(ema_long[i]):
            continue
        # Check bullish alignment (short > mid > long) or bearish (short < mid < long)
        bullish = (ema_short[i] >= ema_mid[i]) and (ema_mid[i] >= ema_long[i])
        bearish = (ema_short[i] <= ema_mid[i]) and (ema_mid[i] <= ema_long[i])

        if bullish or bearish:
            # Measure spread as a fraction of price
            spread = abs(ema_short[i] - ema_long[i]) / ema_long[i] if ema_long[i] != 0 else 0
            alignment[i] = min(spread / 0.02 * 100.0, 100.0)
        else:
            # Partially aligned – give partial credit
            if ema_long[i] != 0:
                spread = abs(ema_short[i] - ema_long[i]) / ema_long[i]
                alignment[i] = min(spread / 0.02 * 50.0, 50.0)
            else:
                alignment[i] = 0.0

    # --- Combine with equal weights ---
    for i in range(n):
        components = []
        if not np.isnan(adx_vals[i]):
            components.append(adx_vals[i])
        if not np.isnan(slope_score[i]):
            components.append(slope_score[i])
        if not np.isnan(alignment[i]):
            components.append(alignment[i])
        if components:
            out[i] = np.mean(components)

    return out
