#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║            NSE Automated Trading System                        ║
║            Powered by AliceBlue API (pya3)                     ║
║                                                                ║
║  Author : Senior Trader - Automated Trading Desk               ║
║  Version: 1.0.0                                                ║
║  Exchange: NSE (National Stock Exchange of India)               ║
╚══════════════════════════════════════════════════════════════════╝

Usage:
    python main.py                    # Start with default config
    python main.py --config path.yaml # Custom config file
    python main.py --mode paper       # Paper trading mode
    python main.py --mode live        # Live trading mode
    python main.py --status           # Show current status
    python main.py --dashboard        # Interactive dashboard
"""

import sys
import os
import signal
import argparse
import time
import threading
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.config_loader import ConfigLoader
from utils.logger import setup_logger
from utils.helpers import is_market_open, format_currency
from engine.trading_engine import TradingEngine


BANNER = r"""
    +-------------------------------------------------------+
    |     _   _ ____  _____   _____              _          |
    |    | \ | / ___|| ____| |_   _| __ __ _  __| | ___     |
    |    |  \| \___ \|  _|     | || '__/ _` |/ _` |/ _ \    |
    |    | |\  |___) | |___    | || | | (_| | (_| |  __/    |
    |    |_| \_|____/|_____|   |_||_|  \__,_|\__,_|\___|    |
    |                                                       |
    |           Automated Trading System v1.0               |
    |           Broker: AliceBlue | Exchange: NSE           |
    +-------------------------------------------------------+
"""


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="NSE Automated Trading System - AliceBlue API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                        Start trading with default config
  python main.py --config custom.yaml   Use custom configuration
  python main.py --mode paper           Run in paper trading mode
  python main.py --mode live            Run in live trading mode (REAL MONEY!)
  python main.py --status               Show system status
  python main.py --dry-run              Validate config without trading
        """
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default="config/settings.yaml",
        help="Path to configuration file (default: config/settings.yaml)"
    )
    parser.add_argument(
        "--mode", "-m",
        type=str,
        choices=["live", "paper"],
        default=None,
        help="Trading mode: 'live' for real trading, 'paper' for simulation"
    )
    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Display current system status and exit"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and connectivity without placing orders"
    )
    parser.add_argument(
        "--dashboard", "-d",
        action="store_true",
        help="Start interactive monitoring dashboard"
    )
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["multi_confirmation", "ema_crossover", "supertrend"],
        default=None,
        help="Override the strategy from config (default: multi_confirmation)"
    )
    parser.add_argument(
        "--watchlist", "-w",
        type=str,
        nargs="+",
        default=None,
        help="Override watchlist symbols (space-separated)"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Override log level"
    )
    return parser.parse_args()


def validate_environment():
    """Validate that required environment and dependencies are available."""
    errors = []

    # Check Python version
    if sys.version_info < (3, 8):
        errors.append(f"Python 3.8+ required, got {sys.version}")

    # Check required packages
    required_packages = {
        "pya3": "pya3",
        "pandas": "pandas",
        "numpy": "numpy",
        "yaml": "PyYAML",
    }
    for import_name, package_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            errors.append(f"Package '{package_name}' not installed. Run: pip install {package_name}")

    # Check .env or environment variables
    user_id = os.environ.get("ALICE_USER_ID", "")
    api_key = os.environ.get("ALICE_API_KEY", "")

    if not user_id or user_id == "your_user_id_here":
        errors.append(
            "ALICE_USER_ID not set. Copy .env.example to .env and add your credentials."
        )
    if not api_key or api_key == "your_api_key_here":
        errors.append(
            "ALICE_API_KEY not set. Copy .env.example to .env and add your credentials."
        )

    return errors


def display_status(engine: TradingEngine):
    """Display current trading system status."""
    print("\n" + "=" * 60)
    print("  TRADING SYSTEM STATUS")
    print("=" * 60)

    status = engine.get_status()
    print(f"\n  Engine State    : {status.get('state', 'UNKNOWN')}")
    print(f"  Trading Mode    : {status.get('mode', 'N/A')}")
    print(f"  Market Open     : {'Yes ✓' if is_market_open() else 'No ✗'}")
    print(f"  Broker Connected: {'Yes ✓' if status.get('broker_connected') else 'No ✗'}")
    print(f"  Strategy        : {status.get('strategy', 'N/A')}")
    print(f"  Watchlist       : {', '.join(status.get('watchlist', []))}")

    positions = engine.get_positions()
    print(f"\n  Open Positions  : {len(positions)}")
    if positions:
        for pos in positions:
            pnl_str = format_currency(pos.get('pnl', 0))
            symbol = pos.get('symbol', 'UNKNOWN')
            qty = pos.get('quantity', 0)
            entry = pos.get('entry_price', 0)
            print(f"    • {symbol}: {qty} @ {entry} | P&L: {pnl_str}")

    pnl = engine.get_pnl()
    print(f"\n  Today's P&L     : {format_currency(pnl.get('daily_pnl', 0))}")
    print(f"  Total Trades    : {pnl.get('total_trades', 0)}")
    print(f"  Win Rate        : {pnl.get('win_rate', 0):.1f}%")
    print("=" * 60 + "\n")


def display_dashboard(engine: TradingEngine):
    """Interactive console dashboard for monitoring."""
    print("\n" + BANNER)
    print("  Dashboard Mode - Press Ctrl+C to exit")
    print("  Commands: [s]tatus  [p]ositions  [b]uy SYMBOL QTY")
    print("            [e]xit SYMBOL  [q]uit  [k]ill-all\n")

    try:
        while True:
            cmd = input("\n  TradeSystem > ").strip().lower()

            if cmd == "s" or cmd == "status":
                display_status(engine)
            elif cmd == "p" or cmd == "positions":
                positions = engine.get_positions()
                if positions:
                    for pos in positions:
                        print(f"    {pos}")
                else:
                    print("    No open positions.")
            elif cmd.startswith("b ") or cmd.startswith("buy "):
                parts = cmd.split()
                if len(parts) >= 3:
                    symbol = parts[1].upper()
                    qty = int(parts[2])
                    result = engine.manual_buy(symbol, qty)
                    print(f"    Order placed: {result}")
                else:
                    print("    Usage: buy SYMBOL QUANTITY")
            elif cmd.startswith("e ") or cmd.startswith("exit "):
                parts = cmd.split()
                if len(parts) >= 2:
                    symbol = parts[1].upper()
                    result = engine.manual_sell(symbol, 0)  # 0 = close entire position
                    print(f"    Exit order: {result}")
                else:
                    print("    Usage: exit SYMBOL")
            elif cmd == "k" or cmd == "kill-all":
                confirm = input("    ⚠️  Square off ALL positions? (yes/no): ").strip()
                if confirm.lower() == "yes":
                    results = engine.square_off_all()
                    print(f"    Squared off: {results}")
                else:
                    print("    Cancelled.")
            elif cmd == "q" or cmd == "quit":
                print("\n    Shutting down gracefully...")
                engine.stop()
                break
            else:
                print("    Unknown command. Try: status, positions, buy, exit, kill-all, quit")

    except KeyboardInterrupt:
        print("\n    Dashboard closed.")


def live_trading_confirmation():
    """Show a confirmation prompt before starting live trading with real money."""
    print("\n" + "=" * 60)
    print("  ⚠️   LIVE TRADING MODE - REAL MONEY AT RISK!   ⚠️")
    print("=" * 60)
    print("""
  You are about to start the automated trading system in
  LIVE mode. This will place REAL orders on NSE through
  your AliceBlue account.

  Please confirm you understand:
  1. Real money will be used for trades
  2. Losses are possible and your responsibility
  3. The system should be monitored during market hours
  4. Risk management parameters are properly configured
    """)
    confirm = input("  Type 'YES I CONFIRM' to proceed: ").strip()
    return confirm == "YES I CONFIRM"


def main():
    """Main entry point for the trading system."""
    print(BANNER)
    args = parse_arguments()

    # ─── Load Environment Variables ──────────────────────────────
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
            print("  [OK] Environment variables loaded from .env")
        except ImportError:
            print("  [WARN] python-dotenv not installed, reading .env manually")
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        os.environ[key.strip()] = value.strip()

    # --- Setup Logging -------------------------------------------
    log_level = args.log_level or os.environ.get("LOG_LEVEL", "INFO")
    logger = setup_logger("TradeSystem", log_level=log_level)
    logger.info("Trading System initializing...")

    # --- Validate Environment ------------------------------------
    errors = validate_environment()
    if errors:
        print("\n  [ERROR] Environment validation failed:")
        for err in errors:
            print(f"     * {err}")
        print("\n  Fix the above issues and try again.")
        sys.exit(1)
    print("  [OK] Environment validation passed")

    # --- Load Configuration --------------------------------------
    try:
        config = ConfigLoader(args.config)
        print(f"  [OK] Configuration loaded from {args.config}")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        print(f"\n  [ERROR] Config error: {e}")
        sys.exit(1)

    # --- Apply Command Line Overrides ----------------------------
    if args.mode:
        config.set("trading.mode", args.mode)
    if args.strategy:
        config.set("strategy.name", args.strategy)
    if args.watchlist:
        config.set("watchlist", args.watchlist)

    trading_mode = config.get("trading.mode", "paper")
    print(f"  [OK] Trading mode: {trading_mode.upper()}")

    # --- Dry Run -------------------------------------------------
    if args.dry_run:
        print("\n  -- DRY RUN MODE --")
        print("  Configuration is valid.")
        print(f"  Strategy   : {config.get('strategy.name', 'multi_confirmation')}")
        print(f"  Watchlist  : {config.get('watchlist', [])}")
        print(f"  Max Loss/Day: {config.get('risk_management.max_daily_loss_pct', 5.0)}%")
        print(f"  Capital/Trade: {format_currency(config.get('trading.capital_per_trade', 20000))}")
        print("\n  [OK] Dry run complete. System is ready for trading.")
        sys.exit(0)

    # --- Live Trading Confirmation -------------------------------
    if trading_mode == "live":
        if not live_trading_confirmation():
            print("\n  Live trading cancelled. Exiting.")
            sys.exit(0)

    # --- Initialize Trading Engine -------------------------------
    try:
        engine = TradingEngine(config_path=args.config)
        print("  [OK] Trading engine initialized")
    except Exception as e:
        logger.error(f"Failed to initialize trading engine: {e}")
        print(f"\n  [ERROR] Engine initialization failed: {e}")
        sys.exit(1)

    # --- Signal Handlers for Graceful Shutdown -------------------
    def signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        print(f"\n  [!] Received {sig_name} - Initiating graceful shutdown...")
        logger.info(f"Received {sig_name}, shutting down...")
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # --- Status Mode ---------------------------------------------
    if args.status:
        display_status(engine)
        sys.exit(0)

    # --- Dashboard Mode ------------------------------------------
    if args.dashboard:
        try:
            engine.start()
            display_dashboard(engine)
        except Exception as e:
            logger.error(f"Dashboard error: {e}")
            engine.stop()
        sys.exit(0)

    # --- Start Trading -------------------------------------------
    print("\n" + "-" * 60)
    print(f"  [*] Starting automated trading...")
    print(f"     Strategy  : {config.get('strategy.name', 'multi_confirmation')}")
    print(f"     Watchlist : {', '.join(config.get('watchlist', []))}")
    print(f"     Mode      : {trading_mode.upper()}")
    print(f"     Market    : {'OPEN' if is_market_open() else 'CLOSED (will wait)'}")
    print("-" * 60 + "\n")

    try:
        engine.start()

        # Keep main thread alive
        print("  System running. Press Ctrl+C to stop.\n")
        while True:
            time.sleep(60)
            # Periodic status log
            if engine._running:
                pnl = engine.get_pnl()
                positions = engine.get_positions()
                logger.info(
                    f"Heartbeat | P&L: {format_currency(pnl.get('daily_pnl', 0))} | "
                    f"Positions: {len(positions)} | "
                    f"Trades: {pnl.get('total_trades', 0)}"
                )

    except KeyboardInterrupt:
        print("\n  Keyboard interrupt received...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\n  [ERROR] Fatal error: {e}")
    finally:
        print("  Shutting down trading engine...")
        engine.stop()
        print("  [OK] Trading system stopped. Goodbye!\n")


if __name__ == "__main__":
    main()
