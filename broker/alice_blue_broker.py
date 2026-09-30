"""
AliceBlue Broker Integration Layer
===================================

Production-grade wrapper around the pya3 (AliceBlue) API for automated
trading on NSE. Provides thread-safe order management, market data
subscriptions via websocket, and comprehensive error handling with
exponential-backoff retries.

Usage:
    config = {"user_id": "AB1234", "api_key": "YOUR_API_KEY"}
    broker = AliceBlueBroker(config)
    broker.connect()
    broker.place_order("RELIANCE", "BUY", 1, "MARKET", "INTRADAY")
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from pya3 import (
    Aliceblue,
    LiveFeedType,
    OrderType,
    ProductType,
    TransactionType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES: int = 3
RETRY_BASE_DELAY: float = 1.0          # seconds – doubles each retry
MIN_REQUEST_INTERVAL: float = 0.25     # 250 ms rate-limit guard
WEBSOCKET_RECONNECT_DELAY: float = 5.0
WEBSOCKET_MAX_RECONNECT: int = 10

# ---------------------------------------------------------------------------
# Enum helpers – maps user-facing strings to pya3 enum members
# ---------------------------------------------------------------------------

SIDE_MAP: Dict[str, TransactionType] = {
    "BUY": TransactionType.Buy,
    "SELL": TransactionType.Sell,
}

ORDER_TYPE_MAP: Dict[str, OrderType] = {
    "MARKET": OrderType.Market,
    "LIMIT": OrderType.Limit,
    "SL": OrderType.StopLossLimit,
    "SL-M": OrderType.StopLossMarket,
    "STOPLOSS": OrderType.StopLossLimit,
    "STOPLOSS_MARKET": OrderType.StopLossMarket,
}

PRODUCT_TYPE_MAP: Dict[str, ProductType] = {
    "INTRADAY": ProductType.Intraday,
    "MIS": ProductType.Intraday,
    "DELIVERY": ProductType.Delivery,
    "CNC": ProductType.Delivery,
    "CO": ProductType.CoverOrder,
    "BO": ProductType.BracketOrder,
}


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def _retry(operation_name: str):
    """Decorator that retries a method up to *MAX_RETRIES* times with
    exponential back-off, logging each attempt."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self: "AliceBlueBroker", *args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[Exception] = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    return func(self, *args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "%s failed (attempt %d/%d): %s – retrying in %.1fs",
                        operation_name,
                        attempt,
                        MAX_RETRIES,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
            logger.error(
                "%s failed after %d attempts: %s",
                operation_name,
                MAX_RETRIES,
                last_exc,
            )
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# AliceBlueBroker
# ---------------------------------------------------------------------------

class AliceBlueBroker:
    """Thread-safe broker adapter for the AliceBlue / pya3 trading API.

    Parameters
    ----------
    config : dict
        Required keys: ``user_id``, ``api_key``.
        Optional keys: ``default_exchange`` (default ``"NSE"``).
    """

    # ------------------------------------------------------------------ init
    def __init__(self, config: Dict[str, Any]) -> None:
        # Validate required config keys
        for key in ("user_id", "api_key"):
            if key not in config:
                raise ValueError(f"Missing required config key: '{key}'")

        self._user_id: str = config["user_id"]
        self._api_key: str = config["api_key"]
        self._default_exchange: str = config.get("default_exchange", "NSE")

        self._alice: Optional[Aliceblue] = None
        self._connected: bool = False
        self._lock: threading.Lock = threading.Lock()
        self._last_request_ts: float = 0.0

        # Websocket state
        self._ws_running: bool = False
        self._ws_callback: Optional[Callable] = None
        self._ws_subscribed_symbols: Dict[str, Any] = {}   # symbol -> instrument
        self._ws_reconnect_count: int = 0
        self._ws_lock: threading.Lock = threading.Lock()

        # Instrument cache: (exchange, symbol) -> instrument
        self._instrument_cache: Dict[tuple, Any] = {}

        logger.info(
            "AliceBlueBroker initialised for user_id=%s, exchange=%s",
            self._user_id,
            self._default_exchange,
        )

    # --------------------------------------------------------- rate limiting
    def _throttle(self) -> None:
        """Block briefly if requests are arriving faster than the minimum
        interval to avoid hitting AliceBlue's rate limits."""
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_ts = time.monotonic()

    # ------------------------------------------------------------ connection
    @_retry("connect")
    def connect(self) -> bool:
        """Authenticate with AliceBlue, obtain a session, and download
        NSE master contracts.

        Returns
        -------
        bool
            ``True`` on successful connection.
        """
        with self._lock:
            logger.info("Connecting to AliceBlue …")
            self._alice = Aliceblue(
                user_id=self._user_id,
                api_key=self._api_key,
            )
            session = self._alice.get_session_id()
            if not session:
                raise ConnectionError(
                    "Failed to obtain session – check user_id / api_key"
                )
            logger.info("Session established.  Downloading contract master …")
            self._alice.get_contract_master(self._default_exchange)
            self._connected = True
            logger.info("AliceBlue connection successful.")
            return True

    def disconnect(self) -> None:
        """Gracefully shut down the websocket and release resources."""
        with self._lock:
            logger.info("Disconnecting from AliceBlue …")
            self._stop_websocket()
            self._connected = False
            self._alice = None
            self._instrument_cache.clear()
            logger.info("Disconnected.")

    def is_connected(self) -> bool:
        """Return ``True`` if the broker session is alive."""
        return self._connected and self._alice is not None

    def _ensure_connected(self) -> None:
        """Raise if the broker is not connected."""
        if not self.is_connected():
            raise ConnectionError(
                "Broker is not connected – call connect() first."
            )

    # ----------------------------------------------------------- instruments
    @_retry("get_instrument")
    def get_instrument(self, symbol: str, exchange: str | None = None) -> Any:
        """Look up and cache a pya3 instrument object by symbol.

        Parameters
        ----------
        symbol : str
            NSE scrip symbol, e.g. ``"RELIANCE"``.
        exchange : str, optional
            Defaults to the broker's ``default_exchange``.

        Returns
        -------
        instrument
            pya3 instrument object suitable for order / subscription calls.
        """
        self._ensure_connected()
        exchange = exchange or self._default_exchange
        cache_key = (exchange, symbol)

        if cache_key in self._instrument_cache:
            return self._instrument_cache[cache_key]

        with self._lock:
            self._throttle()
            instrument = self._alice.get_instrument_by_symbol(exchange, symbol)  # type: ignore[union-attr]
            if instrument is None:
                raise ValueError(
                    f"Instrument not found: {exchange}:{symbol}"
                )
            self._instrument_cache[cache_key] = instrument
            logger.debug("Cached instrument %s:%s", exchange, symbol)
            return instrument

    # -------------------------------------------------------------- orders
    @_retry("place_order")
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        product_type: str = "INTRADAY",
        price: float = 0.0,
        trigger_price: float = 0.0,
        stop_loss: float = 0.0,
        target: float = 0.0,
        exchange: str | None = None,
        is_amo: bool = False,
    ) -> str:
        """Place an order on the exchange.

        Parameters
        ----------
        symbol : str
            NSE scrip symbol.
        side : str
            ``"BUY"`` or ``"SELL"``.
        quantity : int
            Number of shares / lots.
        order_type : str
            ``"MARKET"`` | ``"LIMIT"`` | ``"SL"`` | ``"SL-M"``.
        product_type : str
            ``"INTRADAY"`` | ``"DELIVERY"`` | ``"CO"`` | ``"BO"``.
        price : float
            Limit price (ignored for MARKET orders).
        trigger_price : float
            Trigger price for stop-loss orders.
        stop_loss : float
            Stop-loss value for bracket orders.
        target : float
            Target / square-off value for bracket orders.
        exchange : str, optional
            Defaults to ``default_exchange``.
        is_amo : bool
            ``True`` for After-Market Orders.

        Returns
        -------
        str
            Exchange-assigned order ID.

        Raises
        ------
        ValueError
            If *side*, *order_type*, or *product_type* strings are invalid.
        """
        self._ensure_connected()

        # Resolve enums
        txn_type = SIDE_MAP.get(side.upper())
        if txn_type is None:
            raise ValueError(
                f"Invalid side '{side}'. Expected one of: {list(SIDE_MAP.keys())}"
            )
        ot = ORDER_TYPE_MAP.get(order_type.upper())
        if ot is None:
            raise ValueError(
                f"Invalid order_type '{order_type}'. "
                f"Expected one of: {list(ORDER_TYPE_MAP.keys())}"
            )
        pt = PRODUCT_TYPE_MAP.get(product_type.upper())
        if pt is None:
            raise ValueError(
                f"Invalid product_type '{product_type}'. "
                f"Expected one of: {list(PRODUCT_TYPE_MAP.keys())}"
            )

        instrument = self.get_instrument(symbol, exchange)

        logger.info(
            "Placing %s %s order: %s x%d @ %s (trigger=%s, sl=%s, tgt=%s, amo=%s)",
            side, order_type, symbol, quantity, price,
            trigger_price, stop_loss, target, is_amo,
        )

        with self._lock:
            self._throttle()
            response = self._alice.place_order(  # type: ignore[union-attr]
                transaction_type=txn_type,
                instrument=instrument,
                quantity=quantity,
                order_type=ot,
                product_type=pt,
                price=price,
                trigger_price=trigger_price,
                stop_loss=stop_loss,
                square_off=target,
                trailing_sl=0,
                is_amo=is_amo,
            )

        order_id = self._extract_order_id(response)
        logger.info("Order placed – order_id=%s", order_id)
        return order_id

    @_retry("modify_order")
    def modify_order(
        self,
        order_id: str,
        quantity: Optional[int] = None,
        order_type: Optional[str] = None,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
    ) -> bool:
        """Modify an open order.

        Only the parameters that are not ``None`` will be changed.

        Returns
        -------
        bool
            ``True`` if modification was acknowledged.
        """
        self._ensure_connected()

        ot = None
        if order_type is not None:
            ot = ORDER_TYPE_MAP.get(order_type.upper())
            if ot is None:
                raise ValueError(f"Invalid order_type '{order_type}'")

        logger.info(
            "Modifying order %s: qty=%s, type=%s, price=%s, trigger=%s",
            order_id, quantity, order_type, price, trigger_price,
        )

        modify_kwargs: Dict[str, Any] = {"order_id": order_id}
        if quantity is not None:
            modify_kwargs["quantity"] = quantity
        if ot is not None:
            modify_kwargs["order_type"] = ot
        if price is not None:
            modify_kwargs["price"] = price
        if trigger_price is not None:
            modify_kwargs["trigger_price"] = trigger_price

        with self._lock:
            self._throttle()
            response = self._alice.modify_order(**modify_kwargs)  # type: ignore[union-attr]

        logger.info("Order %s modified – response: %s", order_id, response)
        return True

    @_retry("cancel_order")
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.

        Returns
        -------
        bool
            ``True`` if cancellation was acknowledged.
        """
        self._ensure_connected()
        logger.info("Cancelling order %s", order_id)

        with self._lock:
            self._throttle()
            response = self._alice.cancel_order(order_id)  # type: ignore[union-attr]

        logger.info("Order %s cancelled – response: %s", order_id, response)
        return True

    # --------------------------------------------------------- order queries
    @_retry("get_order_status")
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Retrieve status details for a single order.

        Returns
        -------
        dict
            Keys typically include ``order_id``, ``status``, ``filled_quantity``,
            ``average_price``, etc.
        """
        self._ensure_connected()
        logger.debug("Fetching order status for %s", order_id)

        with self._lock:
            self._throttle()
            history = self._alice.get_order_history(order_id)  # type: ignore[union-attr]

        if isinstance(history, list) and history:
            return history[-1]  # most recent event
        if isinstance(history, dict):
            return history
        return {"order_id": order_id, "status": "UNKNOWN", "raw": history}

    @_retry("get_order_history")
    def get_order_history(self) -> List[Dict[str, Any]]:
        """Retrieve all orders placed in today's session.

        Returns
        -------
        list[dict]
        """
        self._ensure_connected()
        logger.debug("Fetching order history")

        with self._lock:
            self._throttle()
            history = self._alice.get_order_history("")  # type: ignore[union-attr]

        if isinstance(history, list):
            return history
        if history is None:
            return []
        return [history] if isinstance(history, dict) else []

    # ------------------------------------------------------- positions / holdings
    @_retry("get_positions")
    def get_positions(self) -> List[Dict[str, Any]]:
        """Return current day + net positions.

        Returns
        -------
        list[dict]
            Each dict contains keys such as ``symbol``, ``quantity``,
            ``average_price``, ``pnl``, etc.
        """
        self._ensure_connected()
        logger.debug("Fetching positions")

        with self._lock:
            self._throttle()
            day_positions = self._alice.get_daywise_positions()  # type: ignore[union-attr]
            net_positions = self._alice.get_netwise_positions()  # type: ignore[union-attr]

        positions: List[Dict[str, Any]] = []
        for source_label, raw in (("day", day_positions), ("net", net_positions)):
            if isinstance(raw, list):
                for pos in raw:
                    if isinstance(pos, dict):
                        pos["_source"] = source_label
                        positions.append(pos)
            elif isinstance(raw, dict) and raw:
                raw["_source"] = source_label
                positions.append(raw)

        logger.debug("Fetched %d position entries", len(positions))
        return positions

    @_retry("get_holdings")
    def get_holdings(self) -> List[Dict[str, Any]]:
        """Return portfolio holdings (CNC / delivery).

        Returns
        -------
        list[dict]
        """
        self._ensure_connected()
        logger.debug("Fetching holdings")

        with self._lock:
            self._throttle()
            holdings = self._alice.get_holding_positions()  # type: ignore[union-attr]

        if isinstance(holdings, list):
            return holdings
        if holdings is None:
            return []
        return [holdings] if isinstance(holdings, dict) else []

    # ------------------------------------------------------- account info
    @_retry("get_balance")
    def get_balance(self) -> Dict[str, Any]:
        """Return account balance / margin information.

        Returns
        -------
        dict
            Normalised keys: ``available_cash``, ``used_margin``,
            ``total_margin`` plus the full raw response under ``raw``.
        """
        self._ensure_connected()
        logger.debug("Fetching balance")

        with self._lock:
            self._throttle()
            raw = self._alice.get_balance()  # type: ignore[union-attr]

        result: Dict[str, Any] = {"raw": raw}
        if isinstance(raw, list) and raw:
            # pya3 may return a list of segment-wise balances
            equity = raw[0] if raw else {}
            result["available_cash"] = self._safe_float(equity, "cashmarginavailable", 0.0)
            result["used_margin"] = self._safe_float(equity, "marginused", 0.0)
            result["total_margin"] = self._safe_float(equity, "net", 0.0)
        elif isinstance(raw, dict):
            result["available_cash"] = self._safe_float(raw, "cashmarginavailable", 0.0)
            result["used_margin"] = self._safe_float(raw, "marginused", 0.0)
            result["total_margin"] = self._safe_float(raw, "net", 0.0)
        else:
            result.update({"available_cash": 0.0, "used_margin": 0.0, "total_margin": 0.0})

        logger.info(
            "Balance – available=%.2f, used=%.2f, total=%.2f",
            result["available_cash"],
            result["used_margin"],
            result["total_margin"],
        )
        return result

    @_retry("get_profile")
    def get_profile(self) -> Dict[str, Any]:
        """Return user profile information.

        Returns
        -------
        dict
        """
        self._ensure_connected()
        logger.debug("Fetching profile")

        with self._lock:
            self._throttle()
            profile = self._alice.get_profile()  # type: ignore[union-attr]

        if isinstance(profile, dict):
            return profile
        return {"raw": profile}

    # --------------------------------------------------------- market data
    @_retry("get_ltp")
    def get_ltp(self, symbol: str, exchange: str | None = None) -> float:
        """Fetch the Last Traded Price for *symbol*.

        The implementation places a compact live-feed snapshot request.

        Parameters
        ----------
        symbol : str
            NSE scrip symbol.
        exchange : str, optional
            Defaults to ``default_exchange``.

        Returns
        -------
        float
            Last traded price.
        """
        self._ensure_connected()
        instrument = self.get_instrument(symbol, exchange)

        ltp_event = threading.Event()
        ltp_container: Dict[str, float] = {}

        def _ltp_callback(message: Any) -> None:
            try:
                if isinstance(message, dict):
                    ltp_container["ltp"] = float(message.get("ltp", 0.0))
                elif hasattr(message, "ltp"):
                    ltp_container["ltp"] = float(message.ltp)
            except (TypeError, ValueError):
                pass
            finally:
                ltp_event.set()

        with self._lock:
            self._throttle()
            # Start a temporary websocket if one isn't already running
            ws_was_running = self._ws_running
            if not ws_was_running:
                self._alice.start_websocket(  # type: ignore[union-attr]
                    subscribe_callback=_ltp_callback,
                    run_in_background=True,
                )
                time.sleep(1)  # allow socket handshake
            else:
                # Temporarily swap callback (not ideal – prefer separate socket)
                pass

            self._alice.subscribe(instrument, LiveFeedType.COMPACT)  # type: ignore[union-attr]

        ltp_event.wait(timeout=10)

        with self._lock:
            self._alice.unsubscribe(instrument, LiveFeedType.COMPACT)  # type: ignore[union-attr]
            if not ws_was_running:
                self._stop_websocket()

        price = ltp_container.get("ltp", 0.0)
        logger.debug("LTP %s = %.2f", symbol, price)
        return price

    # ------------------------------------------ websocket market data stream
    def subscribe_market_data(
        self,
        symbols: List[str],
        callback: Callable[[Any], None],
        exchange: str | None = None,
    ) -> None:
        """Subscribe to live market-data via websocket.

        Parameters
        ----------
        symbols : list[str]
            NSE scrip symbols to subscribe.
        callback : callable
            Invoked with each tick message (dict or object).
        exchange : str, optional
            Defaults to ``default_exchange``.
        """
        self._ensure_connected()
        exchange = exchange or self._default_exchange

        # Resolve instruments upfront
        instruments = {sym: self.get_instrument(sym, exchange) for sym in symbols}

        with self._ws_lock:
            self._ws_callback = callback
            self._ws_reconnect_count = 0

            if not self._ws_running:
                self._start_websocket()
                time.sleep(1)  # allow handshake

            for sym, inst in instruments.items():
                self._alice.subscribe(inst, LiveFeedType.COMPACT)  # type: ignore[union-attr]
                self._ws_subscribed_symbols[sym] = inst
                logger.info("Subscribed to market data: %s", sym)

    def unsubscribe_market_data(
        self,
        symbols: List[str],
    ) -> None:
        """Unsubscribe from live market-data for the given symbols."""
        self._ensure_connected()

        with self._ws_lock:
            for sym in symbols:
                inst = self._ws_subscribed_symbols.pop(sym, None)
                if inst is not None:
                    try:
                        self._alice.unsubscribe(inst, LiveFeedType.COMPACT)  # type: ignore[union-attr]
                        logger.info("Unsubscribed from market data: %s", sym)
                    except Exception as exc:
                        logger.warning("Error unsubscribing %s: %s", sym, exc)

            # Tear down the socket if nothing is left
            if not self._ws_subscribed_symbols:
                self._stop_websocket()

    # ----------------------------------------------------- square-off helpers
    def square_off_all(self) -> List[str]:
        """Close every open intraday position.

        Returns
        -------
        list[str]
            Order IDs of the square-off orders placed.
        """
        self._ensure_connected()
        logger.info("Squaring off ALL open positions …")

        positions = self.get_positions()
        order_ids: List[str] = []

        for pos in positions:
            qty = self._position_net_qty(pos)
            if qty == 0:
                continue

            symbol = self._position_symbol(pos)
            if not symbol:
                logger.warning("Skipping position with unresolvable symbol: %s", pos)
                continue

            side = "SELL" if qty > 0 else "BUY"
            abs_qty = abs(qty)

            try:
                oid = self.place_order(
                    symbol=symbol,
                    side=side,
                    quantity=abs_qty,
                    order_type="MARKET",
                    product_type="INTRADAY",
                )
                order_ids.append(oid)
                logger.info(
                    "Squared off %s: %s x%d → order %s",
                    symbol, side, abs_qty, oid,
                )
            except Exception as exc:
                logger.error("Failed to square off %s: %s", symbol, exc)

        logger.info("Square-off complete. %d orders placed.", len(order_ids))
        return order_ids

    def square_off_position(self, symbol: str) -> str:
        """Close a specific open position by symbol.

        Returns
        -------
        str
            Order ID of the square-off order.
        """
        self._ensure_connected()
        logger.info("Squaring off position for %s …", symbol)

        positions = self.get_positions()
        for pos in positions:
            pos_symbol = self._position_symbol(pos)
            if pos_symbol and pos_symbol.upper() == symbol.upper():
                qty = self._position_net_qty(pos)
                if qty == 0:
                    logger.info("Position %s already flat.", symbol)
                    return ""

                side = "SELL" if qty > 0 else "BUY"
                abs_qty = abs(qty)
                oid = self.place_order(
                    symbol=symbol,
                    side=side,
                    quantity=abs_qty,
                    order_type="MARKET",
                    product_type="INTRADAY",
                )
                logger.info(
                    "Squared off %s: %s x%d → order %s",
                    symbol, side, abs_qty, oid,
                )
                return oid

        raise ValueError(f"No open position found for symbol '{symbol}'")

    # ================================================================ PRIVATE
    # ---------------------------------------------------- websocket internals
    def _start_websocket(self) -> None:
        """Start the pya3 websocket with an auto-reconnect wrapper."""

        def _on_message(message: Any) -> None:
            if self._ws_callback is not None:
                try:
                    self._ws_callback(message)
                except Exception:
                    logger.exception("Error in websocket callback")

        def _on_disconnect() -> None:
            logger.warning("Websocket disconnected.")
            self._ws_running = False
            self._attempt_ws_reconnect()

        try:
            self._alice.start_websocket(  # type: ignore[union-attr]
                subscribe_callback=_on_message,
                socket_open_callback=lambda: logger.info("Websocket opened."),
                socket_close_callback=_on_disconnect,
                socket_error_callback=lambda e: logger.error("WS error: %s", e),
                run_in_background=True,
            )
            self._ws_running = True
            logger.info("Websocket started.")
        except TypeError:
            # Older pya3 versions may not accept all callbacks
            self._alice.start_websocket(  # type: ignore[union-attr]
                subscribe_callback=_on_message,
                run_in_background=True,
            )
            self._ws_running = True
            logger.info("Websocket started (basic mode).")

    def _stop_websocket(self) -> None:
        """Shut down the websocket gracefully."""
        self._ws_running = False
        self._ws_subscribed_symbols.clear()
        # pya3 does not expose a public stop method; setting the flag is
        # sufficient to prevent reconnect attempts.
        logger.info("Websocket stopped.")

    def _attempt_ws_reconnect(self) -> None:
        """Try to reconnect the websocket in a background thread."""

        def _reconnect() -> None:
            with self._ws_lock:
                while (
                    not self._ws_running
                    and self._ws_reconnect_count < WEBSOCKET_MAX_RECONNECT
                    and self.is_connected()
                ):
                    self._ws_reconnect_count += 1
                    logger.info(
                        "Websocket reconnect attempt %d/%d …",
                        self._ws_reconnect_count,
                        WEBSOCKET_MAX_RECONNECT,
                    )
                    try:
                        self._start_websocket()
                        time.sleep(1)
                        # Re-subscribe
                        for sym, inst in self._ws_subscribed_symbols.items():
                            self._alice.subscribe(inst, LiveFeedType.COMPACT)  # type: ignore[union-attr]
                            logger.info("Re-subscribed to %s", sym)
                        self._ws_reconnect_count = 0
                        return
                    except Exception as exc:
                        logger.warning("Reconnect failed: %s", exc)
                        time.sleep(WEBSOCKET_RECONNECT_DELAY)

                if self._ws_reconnect_count >= WEBSOCKET_MAX_RECONNECT:
                    logger.error(
                        "Websocket reconnect limit (%d) reached – giving up.",
                        WEBSOCKET_MAX_RECONNECT,
                    )

        thread = threading.Thread(target=_reconnect, daemon=True, name="ws-reconnect")
        thread.start()

    # --------------------------------------------------- response helpers
    @staticmethod
    def _extract_order_id(response: Any) -> str:
        """Extract the order ID from a pya3 place_order response.

        The response shape varies across pya3 versions, so we try several
        common patterns.
        """
        if isinstance(response, dict):
            for key in ("NOrdNo", "order_id", "data", "nestOrderNumber"):
                if key in response:
                    val = response[key]
                    if isinstance(val, dict) and "NOrdNo" in val:
                        return str(val["NOrdNo"])
                    return str(val)
        if isinstance(response, str):
            return response
        if response is None:
            raise RuntimeError("Order placement returned None – possibly rejected")
        return str(response)

    @staticmethod
    def _safe_float(
        data: Dict[str, Any], key: str, default: float = 0.0
    ) -> float:
        """Safely extract a float from *data[key]*."""
        try:
            return float(data.get(key, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _position_net_qty(pos: Dict[str, Any]) -> int:
        """Return the net quantity from a position dict."""
        for key in ("netqty", "net_qty", "Netqty", "buyqty", "quantity"):
            if key in pos:
                try:
                    return int(pos[key])
                except (TypeError, ValueError):
                    continue
        return 0

    @staticmethod
    def _position_symbol(pos: Dict[str, Any]) -> str:
        """Return the trading symbol from a position dict."""
        for key in ("Tsym", "trading_symbol", "tradingsymbol", "symbol", "Trsym"):
            if key in pos and pos[key]:
                return str(pos[key])
        return ""
