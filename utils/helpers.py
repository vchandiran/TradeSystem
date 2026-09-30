"""
Utility helpers for the NSE Automated Trading System.

Provides market-hours checking, currency formatting, tick-size rounding,
transaction-charge estimation, retry decorator, and NSE holiday calendar.
"""

from __future__ import annotations

import functools
import logging
import time
from datetime import date, datetime, time as dt_time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, List, Optional, TypeVar, cast

logger = logging.getLogger("TradeSystem.helpers")

# ---------------------------------------------------------------------------
# NSE Holidays (2024-2026)
# Source: https://www.nseindia.com/resources/exchange-communication-holidays
# ---------------------------------------------------------------------------
NSE_HOLIDAYS: List[date] = [
    # ---- 2024 ----
    date(2024, 1, 26),   # Republic Day
    date(2024, 3, 8),    # Maha Shivaratri
    date(2024, 3, 25),   # Holi
    date(2024, 3, 29),   # Good Friday
    date(2024, 4, 11),   # Id-Ul-Fitr (Ramadan)
    date(2024, 4, 14),   # Dr. Ambedkar Jayanti
    date(2024, 4, 17),   # Ram Navami
    date(2024, 4, 21),   # Mahavir Jayanti
    date(2024, 5, 1),    # Maharashtra Day
    date(2024, 5, 23),   # Buddha Purnima
    date(2024, 6, 17),   # Eid-Ul-Adha (Bakri Id)
    date(2024, 7, 17),   # Muharram
    date(2024, 8, 15),   # Independence Day
    date(2024, 9, 16),   # Milad-Un-Nabi
    date(2024, 10, 2),   # Mahatma Gandhi Jayanti
    date(2024, 10, 12),  # Dussehra
    date(2024, 11, 1),   # Diwali (Laxmi Pujan)
    date(2024, 11, 15),  # Guru Nanak Jayanti
    date(2024, 12, 25),  # Christmas
    # ---- 2025 ----
    date(2025, 2, 26),   # Maha Shivaratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramadan)
    date(2025, 4, 10),   # Mahavir Jayanti
    date(2025, 4, 14),   # Dr. Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 6, 7),    # Eid-Ul-Adha (Bakri Id)
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Mahatma Gandhi Jayanti / Dussehra
    date(2025, 10, 21),  # Diwali (Laxmi Pujan)
    date(2025, 10, 22),  # Diwali (Balipratipada)
    date(2025, 11, 5),   # Guru Nanak Jayanti
    date(2025, 12, 25),  # Christmas
    # ---- 2026 ----
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 17),   # Maha Shivaratri
    date(2026, 3, 4),    # Holi
    date(2026, 3, 20),   # Id-Ul-Fitr (Ramadan)
    date(2026, 3, 30),   # Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 27),   # Eid-Ul-Adha (Bakri Id)
    date(2026, 8, 15),   # Independence Day
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 9),   # Dussehra
    date(2026, 10, 28),  # Diwali (Laxmi Pujan)
    date(2026, 11, 25),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
]

_NSE_HOLIDAY_SET = frozenset(NSE_HOLIDAYS)

# Market timing constants (IST)
_MARKET_OPEN = dt_time(9, 15)
_MARKET_CLOSE = dt_time(15, 30)


# ---------------------------------------------------------------------------
# Market Hours (IST)
# ---------------------------------------------------------------------------

try:
    from zoneinfo import ZoneInfo
    _IST_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    _IST_TZ = None


def get_ist_now() -> datetime:
    """Return current datetime in Indian Standard Time (IST)."""
    if _IST_TZ:
        return datetime.now(_IST_TZ)
    return datetime.now()


def is_market_open(now: Optional[datetime] = None) -> bool:
    """Return ``True`` if the NSE equity market is currently open.

    Checks against:
    * Monday – Friday (weekday check)
    * 09:15 – 15:30 IST
    * NSE holiday calendar (2024-2026)
    """
    if now is None:
        now = get_ist_now()

    # Weekend check
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # Holiday check
    if now.date() in _NSE_HOLIDAY_SET:
        return False

    # Time-of-day check (09:15 - 15:30 IST)
    current_time = dt_time(now.hour, now.minute, now.second)
    return _MARKET_OPEN <= current_time <= _MARKET_CLOSE


def get_next_market_open(now: Optional[datetime] = None) -> datetime:
    """Return the :class:`datetime` of the next market open (09:15 IST).

    If the market is currently open, returns the *current day's* open time.

    Parameters
    ----------
    now:
        Reference timestamp.  Defaults to ``datetime.now()``.
    """
    if now is None:
        now = datetime.now()

    candidate = now.date()

    # If today's open hasn't passed yet, today might be it
    if now.time() < _MARKET_OPEN:
        if candidate.weekday() < 5 and candidate not in _NSE_HOLIDAY_SET:
            return datetime.combine(candidate, _MARKET_OPEN)

    # Otherwise, start from tomorrow
    candidate += timedelta(days=1)

    # Walk forward until we find a trading day (bounded at 15 days)
    for _ in range(15):
        if candidate.weekday() < 5 and candidate not in _NSE_HOLIDAY_SET:
            return datetime.combine(candidate, _MARKET_OPEN)
        candidate += timedelta(days=1)

    # Fallback – should never happen within 15 days
    return datetime.combine(candidate, _MARKET_OPEN)


# ---------------------------------------------------------------------------
# Currency Formatting
# ---------------------------------------------------------------------------

def format_currency(amount: float) -> str:
    """Format *amount* in Indian-rupee style with the ₹ symbol.

    Uses the Indian numbering system (lakhs / crores).

    Examples
    --------
    >>> format_currency(1234567.89)
    '₹12,34,567.89'
    >>> format_currency(-500.5)
    '-₹500.50'
    """
    negative = amount < 0
    amount = abs(amount)

    # Split integer and fractional parts
    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    int_part, _, dec_part = str(d).partition(".")
    dec_part = dec_part or "00"

    # Indian grouping: last 3 digits, then groups of 2
    if len(int_part) <= 3:
        formatted_int = int_part
    else:
        last3 = int_part[-3:]
        remaining = int_part[:-3]
        groups: list[str] = []
        while remaining:
            groups.append(remaining[-2:])
            remaining = remaining[:-2]
        groups.reverse()
        formatted_int = ",".join(groups) + "," + last3

    sign = "-" if negative else ""
    return f"{sign}Rs. {formatted_int}.{dec_part}"


# ---------------------------------------------------------------------------
# Tick Size Rounding
# ---------------------------------------------------------------------------

def round_to_tick_size(price: float, tick_size: float = 0.05) -> float:
    """Round *price* to the nearest multiple of *tick_size*.

    Parameters
    ----------
    price:
        Raw price value.
    tick_size:
        Exchange tick size.  NSE equity default is ``0.05``.

    Returns
    -------
    float
        Price rounded to the nearest tick.
    """
    if tick_size <= 0:
        raise ValueError(f"tick_size must be positive, got {tick_size}")

    d_price = Decimal(str(price))
    d_tick = Decimal(str(tick_size))
    rounded = (d_price / d_tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * d_tick
    return float(rounded)


# ---------------------------------------------------------------------------
# Transaction Charge Estimator
# ---------------------------------------------------------------------------

def calculate_charges(
    quantity: int,
    buy_price: float,
    sell_price: float,
    is_intraday: bool = True,
) -> Dict[str, float]:
    """Estimate NSE equity transaction charges.

    Returns an approximate breakdown of brokerage, STT, exchange
    transaction charges, GST, SEBI fees, and stamp duty.  Rates used are
    indicative and may change; verify with your broker.

    Parameters
    ----------
    quantity:
        Number of shares.
    buy_price:
        Average buy price per share.
    sell_price:
        Average sell price per share.
    is_intraday:
        ``True`` for intraday (MIS), ``False`` for delivery (CNC).

    Returns
    -------
    dict
        Keys: ``turnover``, ``brokerage``, ``stt``, ``exchange_txn``,
        ``gst``, ``sebi_charges``, ``stamp_duty``, ``total_charges``,
        ``net_pnl``, ``gross_pnl``.
    """
    buy_value = quantity * buy_price
    sell_value = quantity * sell_price
    turnover = buy_value + sell_value
    gross_pnl = (sell_price - buy_price) * quantity

    # --- Brokerage (flat ₹20 per order or 0.03% of turnover, lower) ---
    brokerage_buy = min(20.0, buy_value * 0.0003)
    brokerage_sell = min(20.0, sell_value * 0.0003)
    brokerage = round(brokerage_buy + brokerage_sell, 2)

    # --- STT (Securities Transaction Tax) ---
    if is_intraday:
        # 0.025% on sell side
        stt = round(sell_value * 0.00025, 2)
    else:
        # 0.1% on both sides
        stt = round(turnover * 0.001, 2)

    # --- Exchange Transaction Charges (NSE: ~0.00345%) ---
    exchange_txn = round(turnover * 0.0000345, 2)

    # --- GST (18% on brokerage + exchange txn) ---
    gst = round((brokerage + exchange_txn) * 0.18, 2)

    # --- SEBI Charges (₹10 per crore) ---
    sebi_charges = round(turnover * 0.000001, 2)

    # --- Stamp Duty (0.003% on buy side for intraday, 0.015% delivery) ---
    if is_intraday:
        stamp_duty = round(buy_value * 0.00003, 2)
    else:
        stamp_duty = round(buy_value * 0.00015, 2)

    total_charges = round(
        brokerage + stt + exchange_txn + gst + sebi_charges + stamp_duty, 2
    )
    net_pnl = round(gross_pnl - total_charges, 2)

    return {
        "turnover": round(turnover, 2),
        "gross_pnl": round(gross_pnl, 2),
        "brokerage": brokerage,
        "stt": stt,
        "exchange_txn": exchange_txn,
        "gst": gst,
        "sebi_charges": sebi_charges,
        "stamp_duty": stamp_duty,
        "total_charges": total_charges,
        "net_pnl": net_pnl,
    }


# ---------------------------------------------------------------------------
# Retry Decorator
# ---------------------------------------------------------------------------

F = TypeVar("F", bound=Callable[..., Any])


def retry_on_failure(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[F], F]:
    """Decorator that retries the wrapped function on failure.

    Parameters
    ----------
    max_retries:
        Maximum number of retry attempts.
    delay:
        Initial delay (seconds) between retries.
    backoff:
        Multiplicative backoff factor applied to *delay* after each retry.
    exceptions:
        Tuple of exception types that trigger a retry.

    Example
    -------
    >>> @retry_on_failure(max_retries=3, delay=0.5)
    ... def flaky_api_call():
    ...     ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_exc: Optional[BaseException] = None
            for attempt in range(1, max_retries + 2):  # 1 initial + max_retries
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt > max_retries:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__name__,
                            max_retries + 1,
                            exc,
                        )
                        raise
                    logger.warning(
                        "%s attempt %d/%d failed (%s). Retrying in %.1fs…",
                        func.__name__,
                        attempt,
                        max_retries + 1,
                        exc,
                        current_delay,
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff
            # Should not reach here, but satisfy type checker
            raise last_exc  # type: ignore[misc]

        return cast(F, wrapper)

    return decorator
