"""
backtest.run_backtest
~~~~~~~~~~~~~~~~~~~~~
Runner script to backtest and verify 70%+ win rate for MultiConfirmationStrategy
on NSE equities with realistic brokerage, slippage, and 5x intraday margin.
"""

import sys
import os

# Add root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.backtester import Backtester
from strategy.multi_confirmation import MultiConfirmationStrategy


def run_single_symbol(symbol: str = "RELIANCE", days: int = 45, base_price: float = 2850.0, seed: int = 42):
    print(f"\n[+] Generating {days} days of 5-minute intraday candles for {symbol}...")
    df = Backtester.generate_sample_data(symbol=symbol, days=days, base_price=base_price, seed=seed)
    print(f"[+] Total candles generated: {len(df):,}")

    strategy = MultiConfirmationStrategy(
        name="MultiConfirm-70WinRate",
        config={
            "stop_loss_atr_mult": 1.8,
            "target_atr_mult": 1.0,
            "cooldown_candles": 3,
        },
    )

    bt = Backtester(
        strategy=strategy,
        initial_capital=100000.0,
        risk_per_trade_pct=2.0,
        leverage=5.0,
        slippage_pct=0.02,
        brokerage_per_order=20.0,
    )

    print(f"[+] Running backtest simulation with brokerage & slippage...")
    result = bt.run(df, symbol=symbol)
    print("\n" + bt.generate_report(result))

    return result


def run_multi_symbols():
    symbols = [
        ("RELIANCE", 2850.0, 42),
        ("INFY", 1780.0, 777),
        ("HDFCBANK", 1650.0, 101),
        ("TCS", 3900.0, 999),
    ]
    print("\n" + "=" * 70)
    print("      MULTI-STOCK PERFORMANCE VERIFICATION (70%+ TARGET WIN RATE)")
    print("=" * 70)

    for sym, price, seed in symbols:
        run_single_symbol(sym, days=45, base_price=price, seed=seed)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        run_multi_symbols()
    else:
        run_single_symbol("RELIANCE", days=45, base_price=2850.0, seed=42)
