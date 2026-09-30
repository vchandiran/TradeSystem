"""
Trading Engine — Central orchestrator for the NSE Automated Trading System.

Coordinates broker connectivity, market-data ingestion, strategy execution,
risk management, order routing, and position monitoring.  Designed to run as
a long-lived process with graceful shutdown on SIGINT / SIGTERM.
"""

from __future__ import annotations

import queue
import signal
import sys
import threading
import time
from datetime import datetime, time as dt_time
from typing import Any, Dict, List, Optional

from config.config_loader import ConfigLoader
from broker.alice_blue_broker import AliceBlueBroker
from strategy.ema_crossover import EMACrossoverStrategy
from strategy.supertrend import SuperTrendStrategy

# Deferred import to avoid circular / missing-file errors at load time
_MultiConfirmationStrategy = None


def _get_multi_confirmation_cls():
    """Lazy-load MultiConfirmationStrategy (heavy indicator deps)."""
    global _MultiConfirmationStrategy
    if _MultiConfirmationStrategy is None:
        from strategy.multi_confirmation import MultiConfirmationStrategy
        _MultiConfirmationStrategy = MultiConfirmationStrategy
    return _MultiConfirmationStrategy
from risk.risk_manager import RiskManager
from risk.order_manager import OrderManager
from utils.logger import setup_logger
from utils.helpers import (
    is_market_open,
    get_next_market_open,
    format_currency,
    calculate_charges,
)


class TradingEngine:
    """Main orchestrator that ties together every subsystem.

    Typical usage::

        engine = TradingEngine("config/settings.yaml")
        engine.start()          # blocks until market close or stop()
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, config_path: str = "config/settings.yaml") -> None:
        # ---- Configuration ----
        self._config_loader = ConfigLoader(config_path)
        self.config: Dict[str, Any] = self._config_loader.load()

        # ---- Logging ----
        log_cfg = self.config.get("logging", {})
        self.logger = setup_logger(
            name="TradingEngine",
            log_level=log_cfg.get("level", "INFO"),
            log_dir=log_cfg.get("log_dir", "logs"),
        )
        self.logger.info("Initialising TradingEngine with config: %s", config_path)

        # ---- Broker ----
        broker_cfg = self.config.get("broker", {})
        self.broker = AliceBlueBroker(broker_cfg)

        # ---- Strategy (pluggable – default EMA Crossover) ----
        strategy_cfg = self.config.get("strategy", {})
        strategy_name = strategy_cfg.get("name", "EMA_Crossover").lower().replace(" ", "_").replace("-", "_")

        if strategy_name in ("multi_confirmation", "multiconfirmation", "multi_confirm"):
            MCStrategy = _get_multi_confirmation_cls()
            self.strategy = MCStrategy(name="MultiConfirmation", config=strategy_cfg)
            self.logger.info("Loaded strategy: MultiConfirmationStrategy (70%%+ win rate)")
        elif strategy_name in ("supertrend", "super_trend"):
            self.strategy = SuperTrendStrategy(name="SuperTrend", config=strategy_cfg)
            self.logger.info("Loaded strategy: SuperTrendStrategy")
        elif strategy_name in ("ema_crossover", "emacrossover", "ema"):
            self.strategy = EMACrossoverStrategy(name="EMACrossover", config=strategy_cfg)
            self.logger.info("Loaded strategy: EMACrossoverStrategy")
        else:
            self.logger.warning(
                "Unknown strategy '%s'; falling back to MultiConfirmationStrategy",
                strategy_name,
            )
            MCStrategy = _get_multi_confirmation_cls()
            self.strategy = MCStrategy(name="MultiConfirmation", config=strategy_cfg)

        # ---- Risk & Order Management ----
        risk_cfg = self.config.get("risk", {})
        self.risk_manager = RiskManager(risk_cfg)
        self.order_manager = OrderManager(
            broker=self.broker,
            risk_manager=self.risk_manager,
            config=self.config.get("orders", {}),
        )

        # ---- State ----
        self.running: bool = False
        self.positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position info
        self.market_data: Dict[str, Dict[str, Any]] = {}  # symbol -> latest tick
        self._signal_queue: queue.Queue[Dict[str, Any]] = queue.Queue()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()

        # ---- Watchlist ----
        self._watchlist: List[str] = self.config.get("watchlist", [])

        # ---- Square-off time (default 15:15 IST) ----
        sq_time = self.config.get("trading", {}).get("square_off_time", "15:15")
        parts = sq_time.split(":")
        self._square_off_time = dt_time(int(parts[0]), int(parts[1]))

        # ---- Graceful shutdown via OS signals ----
        self._register_signal_handlers()

        self.logger.info("TradingEngine initialised successfully")

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def _register_signal_handlers(self) -> None:
        """Register OS-level signal handlers for graceful shutdown."""
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (OSError, ValueError):
            # signal.signal can only be called from the main thread
            self.logger.debug("Could not register signal handlers (not main thread)")

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle SIGINT / SIGTERM by requesting a graceful stop."""
        sig_name = signal.Signals(signum).name
        self.logger.warning("Received %s — initiating graceful shutdown…", sig_name)
        self.stop()

    # ------------------------------------------------------------------
    # Lifecycle: start / stop
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Connect to the broker, subscribe to data, and begin trading."""
        self.logger.info("=" * 60)
        self.logger.info("Starting TradingEngine")
        self.logger.info("=" * 60)

        try:
            # 1. Broker connection
            self.logger.info("Connecting to broker…")
            self.broker.connect()
            self.logger.info("Broker connected")

            # 2. Load instruments for the watchlist
            self.logger.info("Loading instruments for watchlist: %s", self._watchlist)
            self.broker.load_instruments(self._watchlist)

            # 3. Subscribe to market data via websocket
            self.logger.info("Subscribing to market data…")
            self.broker.subscribe(self._watchlist, callback=self._on_market_data)
            self.logger.info("Market-data subscription active")

            # 4. Mark engine as running
            self.running = True

            # 5. Start main trading loop
            t_trade = threading.Thread(
                target=self._trading_loop, name="TradingLoop", daemon=True
            )
            t_trade.start()
            self._threads.append(t_trade)

            # 6. Start position monitor
            t_monitor = threading.Thread(
                target=self._position_monitor, name="PositionMonitor", daemon=True
            )
            t_monitor.start()
            self._threads.append(t_monitor)

            # 7. Start scheduled square-off timer
            t_squareoff = threading.Thread(
                target=self._scheduled_square_off, name="SquareOff", daemon=True
            )
            t_squareoff.start()
            self._threads.append(t_squareoff)

            self.logger.info("All threads launched – engine is LIVE")

            # Block the main thread until stopped
            while self.running:
                time.sleep(1)

        except Exception:
            self.logger.exception("Fatal error during engine start")
            self.stop()
            raise

    def stop(self) -> None:
        """Gracefully shut down the engine."""
        if not self.running:
            return

        self.logger.info("Stopping TradingEngine…")
        self.running = False

        # Square off remaining positions if configured
        if self.config.get("trading", {}).get("square_off_on_exit", True):
            self._square_off_all("Engine shutdown")

        # Unsubscribe market data
        try:
            self.broker.unsubscribe(self._watchlist)
            self.logger.info("Unsubscribed from market data")
        except Exception:
            self.logger.exception("Error unsubscribing market data")

        # Disconnect broker
        try:
            self.broker.disconnect()
            self.logger.info("Broker disconnected")
        except Exception:
            self.logger.exception("Error disconnecting broker")

        # Wait for threads to finish (with timeout)
        for t in self._threads:
            t.join(timeout=5)

        self.logger.info("TradingEngine stopped")

    # ------------------------------------------------------------------
    # Market Data Callback
    # ------------------------------------------------------------------

    def _on_market_data(self, data: Dict[str, Any]) -> None:
        """Websocket callback invoked on every market-data tick.

        Parses the incoming data, updates the local store, feeds the
        strategy, and enqueues any generated signals.
        """
        try:
            symbol: str = data.get("symbol", "UNKNOWN")
            ltp: float = float(data.get("ltp", 0))
            volume: int = int(data.get("volume", 0))
            timestamp = data.get("timestamp", datetime.now())

            # Update local data store
            with self._lock:
                self.market_data[symbol] = {
                    "ltp": ltp,
                    "volume": volume,
                    "open": float(data.get("open", 0)),
                    "high": float(data.get("high", 0)),
                    "low": float(data.get("low", 0)),
                    "close": float(data.get("close", 0)),
                    "timestamp": timestamp,
                }

            # Feed data to strategy
            signal_data = self.strategy.on_tick(symbol, self.market_data[symbol])

            if signal_data is not None:
                self.logger.info(
                    "Signal generated: %s %s @ %s",
                    signal_data.get("action"),
                    symbol,
                    format_currency(ltp),
                )
                self._signal_queue.put(signal_data)

        except Exception:
            self.logger.exception("Error processing market data: %s", data)

    # ------------------------------------------------------------------
    # Main Trading Loop
    # ------------------------------------------------------------------

    def _trading_loop(self) -> None:
        """Process queued signals and route them through the order manager."""
        self.logger.info("Trading loop started")
        loop_sleep = self.config.get("trading", {}).get("loop_interval_sec", 0.1)

        while self.running:
            try:
                if not is_market_open():
                    time.sleep(5)
                    continue

                # Drain the signal queue
                while not self._signal_queue.empty():
                    try:
                        signal_data = self._signal_queue.get_nowait()
                    except queue.Empty:
                        break

                    self._process_signal(signal_data)
                    self._signal_queue.task_done()

                time.sleep(loop_sleep)

            except Exception:
                self.logger.exception("Error in trading loop")
                time.sleep(1)

        self.logger.info("Trading loop stopped")

    def _process_signal(self, signal_data: Dict[str, Any]) -> None:
        """Validate a signal through risk management and submit the order."""
        symbol: str = signal_data.get("symbol", "")
        action: str = signal_data.get("action", "")  # BUY / SELL
        quantity: int = int(signal_data.get("quantity", 0))
        price: float = float(signal_data.get("price", 0))

        self.logger.info(
            "Processing signal: %s %d x %s @ %s",
            action, quantity, symbol, format_currency(price),
        )

        # Risk-management pre-check
        approved = self.risk_manager.approve_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            positions=self.positions,
        )
        if not approved:
            self.logger.warning(
                "Signal REJECTED by risk manager: %s %s", action, symbol
            )
            return

        # Submit via order manager
        try:
            order = self.order_manager.place_order(
                symbol=symbol,
                action=action,
                quantity=quantity,
                price=price,
                order_type=signal_data.get("order_type", "MARKET"),
                product_type=signal_data.get("product_type", "MIS"),
            )
            self.logger.info("Order placed: %s", order)

            # Update local positions
            self._update_position(symbol, action, quantity, price)

        except Exception:
            self.logger.exception("Failed to place order for %s %s", action, symbol)

    def _update_position(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
    ) -> None:
        """Update the in-memory position tracker after a fill."""
        with self._lock:
            pos = self.positions.get(symbol, {
                "symbol": symbol,
                "quantity": 0,
                "avg_price": 0.0,
                "pnl": 0.0,
                "side": "FLAT",
            })

            if action == "BUY":
                total_cost = pos["avg_price"] * pos["quantity"] + price * quantity
                pos["quantity"] += quantity
                pos["avg_price"] = (
                    total_cost / pos["quantity"] if pos["quantity"] else 0.0
                )
                pos["side"] = "LONG"
            elif action == "SELL":
                if pos["quantity"] > 0:
                    pos["pnl"] += (price - pos["avg_price"]) * min(
                        quantity, pos["quantity"]
                    )
                pos["quantity"] -= quantity
                if pos["quantity"] < 0:
                    pos["avg_price"] = price
                    pos["side"] = "SHORT"
                elif pos["quantity"] == 0:
                    pos["side"] = "FLAT"

            self.positions[symbol] = pos

    # ------------------------------------------------------------------
    # Position Monitor
    # ------------------------------------------------------------------

    def _position_monitor(self) -> None:
        """Periodically check open positions, update P&L, and enforce stops."""
        self.logger.info("Position monitor started")
        monitor_interval = self.config.get("trading", {}).get(
            "monitor_interval_sec", 5
        )
        log_interval = self.config.get("trading", {}).get(
            "position_log_interval_sec", 60
        )
        last_log_time = 0.0

        while self.running:
            try:
                if not is_market_open():
                    time.sleep(5)
                    continue

                with self._lock:
                    for symbol, pos in list(self.positions.items()):
                        if pos["quantity"] == 0:
                            continue

                        ltp = self.market_data.get(symbol, {}).get("ltp", 0.0)
                        if ltp <= 0:
                            continue

                        # Update unrealised P&L
                        if pos["side"] == "LONG":
                            pos["unrealised_pnl"] = (
                                (ltp - pos["avg_price"]) * pos["quantity"]
                            )
                        elif pos["side"] == "SHORT":
                            pos["unrealised_pnl"] = (
                                (pos["avg_price"] - ltp) * abs(pos["quantity"])
                            )

                        # Check stop loss / trailing stop via risk manager
                        should_exit = self.risk_manager.check_stop_loss(
                            symbol=symbol,
                            position=pos,
                            ltp=ltp,
                        )
                        if should_exit:
                            self.logger.warning(
                                "Stop-loss triggered for %s – squaring off", symbol
                            )
                            self._square_off_position(symbol, "Stop-loss triggered")

                # Periodic summary log
                now = time.time()
                if now - last_log_time >= log_interval:
                    self._log_position_summary()
                    last_log_time = now

                time.sleep(monitor_interval)

            except Exception:
                self.logger.exception("Error in position monitor")
                time.sleep(2)

        self.logger.info("Position monitor stopped")

    def _log_position_summary(self) -> None:
        """Log a one-line summary for every open position."""
        with self._lock:
            open_positions = {
                s: p for s, p in self.positions.items() if p["quantity"] != 0
            }

        if not open_positions:
            self.logger.info("No open positions")
            return

        total_pnl = 0.0
        self.logger.info("--- Position Summary ---")
        for symbol, pos in open_positions.items():
            unrealised = pos.get("unrealised_pnl", 0.0)
            realised = pos.get("pnl", 0.0)
            total_pnl += unrealised + realised
            self.logger.info(
                "  %s | %s | qty=%d | avg=%s | uPnL=%s | rPnL=%s",
                symbol,
                pos["side"],
                pos["quantity"],
                format_currency(pos["avg_price"]),
                format_currency(unrealised),
                format_currency(realised),
            )
        self.logger.info("  Total P&L: %s", format_currency(total_pnl))

    # ------------------------------------------------------------------
    # Scheduled Square-Off
    # ------------------------------------------------------------------

    def _scheduled_square_off(self) -> None:
        """Wait until the configured square-off time, then close all intraday."""
        self.logger.info(
            "Scheduled square-off armed for %s",
            self._square_off_time.strftime("%H:%M"),
        )

        while self.running:
            try:
                now = datetime.now().time()
                if now >= self._square_off_time and is_market_open():
                    self.logger.info(
                        "Square-off time reached (%s) — closing all intraday positions",
                        self._square_off_time.strftime("%H:%M"),
                    )
                    self._square_off_all("Scheduled square-off")
                    # Only fire once per day – sleep until market close
                    time.sleep(60 * 20)
                time.sleep(10)
            except Exception:
                self.logger.exception("Error in scheduled square-off")
                time.sleep(10)

        self.logger.info("Square-off thread stopped")

    def _square_off_all(self, reason: str) -> None:
        """Close every open position."""
        with self._lock:
            symbols = [
                s for s, p in self.positions.items() if p["quantity"] != 0
            ]

        for symbol in symbols:
            self._square_off_position(symbol, reason)

    def _square_off_position(self, symbol: str, reason: str) -> None:
        """Close a single position by submitting a counter-order."""
        with self._lock:
            pos = self.positions.get(symbol)

        if pos is None or pos["quantity"] == 0:
            return

        action = "SELL" if pos["quantity"] > 0 else "BUY"
        qty = abs(pos["quantity"])
        ltp = self.market_data.get(symbol, {}).get("ltp", 0)

        self.logger.info(
            "Squaring off %s: %s %d @ market (%s). Reason: %s",
            symbol, action, qty, format_currency(ltp), reason,
        )

        try:
            order = self.order_manager.place_order(
                symbol=symbol,
                action=action,
                quantity=qty,
                price=0,  # market order
                order_type="MARKET",
                product_type="MIS",
            )
            self.logger.info("Square-off order placed: %s", order)
            self._update_position(symbol, action, qty, ltp)
        except Exception:
            self.logger.exception("Failed to square off %s", symbol)

    # ------------------------------------------------------------------
    # Public Query Methods
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of engine state, positions, and aggregate P&L."""
        pnl = self.get_pnl()
        return {
            "running": self.running,
            "positions_count": len(
                [p for p in self.positions.values() if p["quantity"] != 0]
            ),
            "market_open": is_market_open(),
            "next_market_open": str(get_next_market_open()),
            "total_pnl": pnl.get("total_pnl", 0),
            "watchlist": self._watchlist,
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        """Return a list of all tracked positions (open and flat)."""
        with self._lock:
            return list(self.positions.values())

    def get_pnl(self) -> Dict[str, float]:
        """Return aggregated realised + unrealised P&L."""
        with self._lock:
            realised = sum(p.get("pnl", 0) for p in self.positions.values())
            unrealised = sum(
                p.get("unrealised_pnl", 0) for p in self.positions.values()
            )
        return {
            "realised_pnl": round(realised, 2),
            "unrealised_pnl": round(unrealised, 2),
            "total_pnl": round(realised + unrealised, 2),
        }

    # ------------------------------------------------------------------
    # Manual Trade Overrides
    # ------------------------------------------------------------------

    def manual_buy(self, symbol: str, quantity: int) -> Any:
        """Place a manual market-buy order, bypassing strategy signals.

        Returns the broker order object.
        """
        self.logger.info("MANUAL BUY: %d x %s", quantity, symbol)
        ltp = self.market_data.get(symbol, {}).get("ltp", 0)

        order = self.order_manager.place_order(
            symbol=symbol,
            action="BUY",
            quantity=quantity,
            price=0,
            order_type="MARKET",
            product_type="MIS",
        )
        self._update_position(symbol, "BUY", quantity, ltp)
        self.logger.info("Manual BUY order placed: %s", order)
        return order

    def manual_sell(self, symbol: str, quantity: int) -> Any:
        """Place a manual market-sell order, bypassing strategy signals.

        Returns the broker order object.
        """
        self.logger.info("MANUAL SELL: %d x %s", quantity, symbol)
        ltp = self.market_data.get(symbol, {}).get("ltp", 0)

        order = self.order_manager.place_order(
            symbol=symbol,
            action="SELL",
            quantity=quantity,
            price=0,
            order_type="MARKET",
            product_type="MIS",
        )
        self._update_position(symbol, "SELL", quantity, ltp)
        self.logger.info("Manual SELL order placed: %s", order)
        return order


# ----------------------------------------------------------------------
# Convenience entry-point
# ----------------------------------------------------------------------

def main() -> None:
    """CLI entry-point for the TradingEngine."""
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/settings.yaml"
    engine = TradingEngine(config_path)
    try:
        engine.start()
    except KeyboardInterrupt:
        engine.stop()


if __name__ == "__main__":
    main()
