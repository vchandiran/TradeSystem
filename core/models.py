"""
core.models
~~~~~~~~~~~
Domain data models for the NSE automated trading system.

All models are immutable-friendly dataclasses with:
  - Proper type hints
  - Computed fields via __post_init__
  - JSON-serialisable ``as_dict()`` helpers
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class OrderSide(Enum):
    """Direction of an order."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Lifecycle status of an order."""
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class PositionStatus(Enum):
    """Status of an open / closed position."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PARTIAL = "PARTIAL"


class SignalType(Enum):
    """Strategy signal classification."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT = "EXIT"


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def _serialize_value(obj: Any) -> Any:
    """Recursively convert non-JSON-native types."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_value(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """A trading signal emitted by a strategy."""

    symbol: str
    signal_type: SignalType
    price: float
    timestamp: datetime
    strategy_name: str
    strength: float = 0.0          # 0.0 – 1.0 confidence score
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(
                f"Signal strength must be in [0, 1], got {self.strength}"
            )
        if isinstance(self.signal_type, str):
            self.signal_type = SignalType(self.signal_type)
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)

    def as_dict(self) -> Dict[str, Any]:
        return {k: _serialize_value(v) for k, v in asdict(self).items()}


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------

@dataclass
class Order:
    """Represents an order placed with the broker."""

    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    order_type: str = "Market"          # Market | Limit | SL | SL-M
    product_type: str = "Intraday"      # Intraday | Delivery | CO | BO
    status: OrderStatus = OrderStatus.PENDING
    timestamp: datetime = field(default_factory=datetime.now)
    broker_order_id: Optional[str] = None
    pnl: float = 0.0
    buy_price: Optional[float] = None
    sell_price: Optional[float] = None
    profit: Optional[float] = None
    profit_pct: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Computed
    order_value: float = field(init=False)

    def __post_init__(self) -> None:
        self.order_value = round(self.price * self.quantity, 2)
        if isinstance(self.side, str):
            self.side = OrderSide(self.side)
        if isinstance(self.status, str):
            self.status = OrderStatus(self.status)
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)

    def as_dict(self) -> Dict[str, Any]:
        return {k: _serialize_value(v) for k, v in asdict(self).items()}

    @staticmethod
    def generate_id() -> str:
        """Generate a unique order ID."""
        return f"ORD-{uuid.uuid4().hex[:12].upper()}"


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

@dataclass
class Position:
    """Tracks a live or closed position."""

    symbol: str
    side: OrderSide
    quantity: int
    entry_price: float
    current_price: float = 0.0
    pnl: float = 0.0
    unrealized_pnl: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    entry_time: datetime = field(default_factory=datetime.now)
    exit_time: Optional[datetime] = None

    # Computed
    pnl_pct: float = field(init=False)

    def __post_init__(self) -> None:
        self._recompute()
        if isinstance(self.side, str):
            self.side = OrderSide(self.side)
        if isinstance(self.status, str):
            self.status = PositionStatus(self.status)
        if isinstance(self.entry_time, str):
            self.entry_time = datetime.fromisoformat(self.entry_time)
        if isinstance(self.exit_time, str):
            self.exit_time = datetime.fromisoformat(self.exit_time)

    def _recompute(self) -> None:
        """Recompute derived P&L fields."""
        if self.current_price and self.entry_price:
            multiplier = 1 if self.side == OrderSide.BUY else -1
            self.unrealized_pnl = round(
                (self.current_price - self.entry_price) * self.quantity * multiplier, 2
            )
            self.pnl_pct = round(
                ((self.current_price - self.entry_price) / self.entry_price) * 100 * multiplier, 2
            )
        else:
            self.pnl_pct = 0.0

    def update_price(self, price: float) -> None:
        """Update current market price and recompute P&L."""
        self.current_price = price
        self._recompute()

    def as_dict(self) -> Dict[str, Any]:
        return {k: _serialize_value(v) for k, v in asdict(self).items()}


# ---------------------------------------------------------------------------
# TradeLog
# ---------------------------------------------------------------------------

@dataclass
class TradeLog:
    """Immutable record of a completed trade (round-trip)."""

    trade_id: str
    symbol: str
    side: OrderSide
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    entry_time: datetime
    exit_time: datetime
    strategy: str = ""
    holding_period: Optional[float] = field(init=False)  # seconds

    def __post_init__(self) -> None:
        if isinstance(self.side, str):
            self.side = OrderSide(self.side)
        if isinstance(self.entry_time, str):
            self.entry_time = datetime.fromisoformat(self.entry_time)
        if isinstance(self.exit_time, str):
            self.exit_time = datetime.fromisoformat(self.exit_time)
        # Compute holding period in seconds
        delta = self.exit_time - self.entry_time
        self.holding_period = round(delta.total_seconds(), 2)

    @property
    def pnl_pct(self) -> float:
        """Return percentage P&L based on entry price."""
        if self.entry_price == 0:
            return 0.0
        return round(
            ((self.exit_price - self.entry_price) / self.entry_price) * 100, 2
        )

    def as_dict(self) -> Dict[str, Any]:
        d = {k: _serialize_value(v) for k, v in asdict(self).items()}
        d["pnl_pct"] = self.pnl_pct
        return d

    @staticmethod
    def generate_id() -> str:
        return f"TRD-{uuid.uuid4().hex[:12].upper()}"


# ---------------------------------------------------------------------------
# MarketData
# ---------------------------------------------------------------------------

@dataclass
class MarketData:
    """A snapshot of market data for a single instrument."""

    symbol: str
    ltp: float                        # Last Traded Price
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0               # Previous close
    volume: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    bid: float = 0.0
    ask: float = 0.0
    oi: int = 0                       # Open Interest

    # Computed
    spread: float = field(init=False)
    change_pct: float = field(init=False)

    def __post_init__(self) -> None:
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)
        self.spread = round(self.ask - self.bid, 2) if self.ask and self.bid else 0.0
        self.change_pct = (
            round(((self.ltp - self.close) / self.close) * 100, 2)
            if self.close
            else 0.0
        )

    def as_dict(self) -> Dict[str, Any]:
        return {k: _serialize_value(v) for k, v in asdict(self).items()}
