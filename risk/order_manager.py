"""
risk.order_manager
~~~~~~~~~~~~~~~~~~
Order lifecycle management for the NSE automated trading system.

Bridges trading signals → risk validation → broker execution → order tracking.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.models import (
    Order,
    OrderSide,
    OrderStatus,
    Signal,
    SignalType,
)
from risk.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class OrderManager:
    """Manages the full order lifecycle from signal to execution.

    Coordinates with :class:`RiskManager` for pre-trade validation and
    with the broker adapter for execution and modification.
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, broker: Any, risk_manager: RiskManager) -> None:
        """
        Parameters
        ----------
        broker
            Broker adapter instance.  Must expose ``place_order``,
            ``modify_order``, ``cancel_order``, and ``square_off_all``
            methods.
        risk_manager
            The shared :class:`RiskManager` instance.
        """
        self._broker = broker
        self._risk: RiskManager = risk_manager

        # order_id → Order
        self._orders: Dict[str, Order] = {}
        self._lock = threading.Lock()

        logger.info("OrderManager initialised")

    # ------------------------------------------------------------------
    # Signal → Order pipeline
    # ------------------------------------------------------------------

    def place_order(
        self,
        signal: Signal,
        capital: float,
    ) -> Optional[Order]:
        """Execute the full signal-to-order pipeline.

        Steps
        -----
        1. Map the signal to an order side.
        2. Validate with the risk manager.
        3. Compute position size, stop-loss, and target.
        4. Submit the order via the broker.
        5. Track the order internally.

        Parameters
        ----------
        signal : Signal
            The strategy signal to act on.
        capital : float
            Available trading capital for position sizing.

        Returns
        -------
        Order or None
            The placed ``Order`` on success, or ``None`` if rejected.
        """
        # --- 1. Determine side ----------------------------------------
        side = self._signal_to_side(signal.signal_type)
        if side is None:
            logger.info(
                "Signal type %s for %s does not map to an actionable order – skipping",
                signal.signal_type.value, signal.symbol,
            )
            return None

        # --- 2. Compute stop-loss & target ----------------------------
        side_str = side.value  # "BUY" or "SELL"
        stop_loss = self._risk.calculate_stop_loss(signal.price, side_str)
        target = self._risk.calculate_target(signal.price, side_str)

        # --- 3. Position sizing ---------------------------------------
        risk_pct = self._risk._cfg.get("risk_per_trade_pct", 1.0)
        quantity = self._risk.calculate_position_size(
            capital, risk_pct, signal.price, stop_loss,
        )
        if quantity <= 0:
            logger.warning(
                "Position size is 0 for %s at %.2f – order skipped",
                signal.symbol, signal.price,
            )
            return None

        # --- 4. Risk validation ---------------------------------------
        order_request: Dict[str, Any] = {
            "symbol": signal.symbol,
            "side": side_str,
            "price": signal.price,
            "quantity": quantity,
            "stop_loss_amount": abs(signal.price - stop_loss) * quantity,
        }

        valid, reason = self._risk.validate_order(order_request)
        if not valid:
            logger.warning(
                "Order for %s rejected by risk manager – %s",
                signal.symbol, reason,
            )
            return None

        # --- 5. Build Order model -------------------------------------
        order = Order(
            order_id=Order.generate_id(),
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            price=signal.price,
            order_type="Market",
            product_type="Intraday",
            status=OrderStatus.PENDING,
            timestamp=datetime.now(),
            metadata={
                "strategy": signal.strategy_name,
                "signal_strength": signal.strength,
                "stop_loss": stop_loss,
                "target": target,
                **signal.metadata,
            },
        )

        # --- 6. Submit to broker --------------------------------------
        try:
            broker_result = self._broker.place_order(
                symbol=order.symbol,
                side=side_str,
                quantity=order.quantity,
                price=order.price,
                order_type=order.order_type,
                product_type=order.product_type,
            )
            order.broker_order_id = str(broker_result.get("order_id", ""))
            order.status = OrderStatus.OPEN
            self._risk.increment_open_positions()

            logger.info(
                "Order placed – %s  %s %s x%d @%.2f  broker_id=%s  "
                "sl=%.2f  tgt=%.2f",
                order.order_id, side_str, order.symbol, order.quantity,
                order.price, order.broker_order_id, stop_loss, target,
            )
        except Exception:
            order.status = OrderStatus.REJECTED
            logger.exception(
                "Broker rejected order %s for %s", order.order_id, order.symbol,
            )

        # --- 7. Track -------------------------------------------------
        self._track_order(order)
        return order

    # ------------------------------------------------------------------
    # Order modification
    # ------------------------------------------------------------------

    def modify_order(self, order_id: str, **kwargs: Any) -> bool:
        """Modify an existing open order via the broker.

        Supported keyword arguments are forwarded to
        ``broker.modify_order`` (e.g. ``price``, ``quantity``,
        ``order_type``).

        Returns
        -------
        bool
            ``True`` if the modification succeeded.
        """
        order = self.get_order(order_id)
        if order is None:
            logger.warning("Cannot modify – order %s not found", order_id)
            return False

        if order.status not in (OrderStatus.PENDING, OrderStatus.OPEN):
            logger.warning(
                "Cannot modify order %s in status %s",
                order_id, order.status.value,
            )
            return False

        try:
            self._broker.modify_order(
                order_id=order.broker_order_id or order.order_id,
                **kwargs,
            )
            # Apply changes locally
            for key, value in kwargs.items():
                if hasattr(order, key):
                    setattr(order, key, value)

            logger.info("Order %s modified – %s", order_id, kwargs)
            return True
        except Exception:
            logger.exception("Failed to modify order %s", order_id)
            return False

    # ------------------------------------------------------------------
    # Order cancellation
    # ------------------------------------------------------------------

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.

        Returns
        -------
        bool
            ``True`` if cancellation succeeded.
        """
        order = self.get_order(order_id)
        if order is None:
            logger.warning("Cannot cancel – order %s not found", order_id)
            return False

        if order.status not in (OrderStatus.PENDING, OrderStatus.OPEN):
            logger.warning(
                "Cannot cancel order %s in status %s",
                order_id, order.status.value,
            )
            return False

        try:
            self._broker.cancel_order(
                order_id=order.broker_order_id or order.order_id,
            )
            order.status = OrderStatus.CANCELLED
            self._risk.decrement_open_positions()

            logger.info("Order %s cancelled", order_id)
            return True
        except Exception:
            logger.exception("Failed to cancel order %s", order_id)
            return False

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_active_orders(self) -> List[Order]:
        """Return all orders in PENDING or OPEN status."""
        with self._lock:
            return [
                o for o in self._orders.values()
                if o.status in (OrderStatus.PENDING, OrderStatus.OPEN)
            ]

    def get_order(self, order_id: str) -> Optional[Order]:
        """Retrieve an order by its internal ID."""
        with self._lock:
            order = self._orders.get(order_id)
        if order is None:
            logger.debug("Order %s not found in tracker", order_id)
        return order

    # ------------------------------------------------------------------
    # Status management
    # ------------------------------------------------------------------

    def update_order_status(self, order_id: str, status: OrderStatus) -> None:
        """Update the status of a tracked order.

        When an order transitions to COMPLETED or CANCELLED the open-
        positions counter in the risk manager is decremented.
        """
        order = self.get_order(order_id)
        if order is None:
            logger.warning(
                "Cannot update status – order %s not found", order_id,
            )
            return

        old_status = order.status
        if isinstance(status, str):
            status = OrderStatus(status)
        order.status = status

        # Adjust open-position counter on terminal states
        if (
            old_status in (OrderStatus.PENDING, OrderStatus.OPEN)
            and status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.REJECTED)
        ):
            self._risk.decrement_open_positions()

        logger.info(
            "Order %s status updated – %s → %s",
            order_id, old_status.value, status.value,
        )

    # ------------------------------------------------------------------
    # Square-off
    # ------------------------------------------------------------------

    def square_off_all(self) -> List[Dict[str, Any]]:
        """Square off all open / pending orders.

        Attempts cancellation first, then delegates full square-off to
        the broker.

        Returns
        -------
        list[dict]
            A result dict per order with ``order_id``, ``success``, and
            optional ``error``.
        """
        results: List[Dict[str, Any]] = []
        active_orders = self.get_active_orders()

        if not active_orders:
            logger.info("No active orders to square off")
            return results

        logger.info(
            "Squaring off %d active order(s)…", len(active_orders),
        )

        for order in active_orders:
            result: Dict[str, Any] = {"order_id": order.order_id, "symbol": order.symbol}
            try:
                self._broker.cancel_order(
                    order_id=order.broker_order_id or order.order_id,
                )
                order.status = OrderStatus.CANCELLED
                self._risk.decrement_open_positions()
                result["success"] = True
                logger.info("Squared off order %s (%s)", order.order_id, order.symbol)
            except Exception as exc:
                result["success"] = False
                result["error"] = str(exc)
                logger.exception(
                    "Failed to square off order %s", order.order_id,
                )
            results.append(result)

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _track_order(self, order: Order) -> None:
        """Store the order for internal tracking."""
        with self._lock:
            self._orders[order.order_id] = order
        logger.debug("Tracking order %s (%s)", order.order_id, order.symbol)

    @staticmethod
    def _signal_to_side(signal_type: SignalType) -> Optional[OrderSide]:
        """Map a :class:`SignalType` to an :class:`OrderSide`.

        Returns ``None`` for HOLD / EXIT signals that do not directly
        produce a new order.
        """
        mapping = {
            SignalType.BUY: OrderSide.BUY,
            SignalType.SELL: OrderSide.SELL,
        }
        return mapping.get(signal_type)
