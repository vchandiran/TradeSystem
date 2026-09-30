"""
backtest.backtester
~~~~~~~~~~~~~~~~~~~
High-performance backtesting engine for validating trading strategy win rates,
P&L, drawdowns, and expectancy on historical or simulated market data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.models import OrderSide, Position, PositionStatus, Signal, SignalType, TradeLog
from strategy.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Statistical summary of backtest execution."""

    strategy_name: str
    symbol: str
    initial_capital: float
    final_capital: float
    total_pnl: float
    pnl_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    avg_win: float
    avg_loss: float
    win_loss_ratio: float
    expectancy: float
    best_trade: float
    worst_trade: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    trade_logs: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)


class Backtester:
    """Executes a strategy against OHLCV data and measures execution performance."""

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_capital: float = 100000.0,
        risk_per_trade_pct: float = 2.0,
        leverage: float = 5.0,
        slippage_pct: float = 0.02,
        brokerage_per_order: float = 20.0,
    ) -> None:
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.risk_per_trade_pct = risk_per_trade_pct
        self.leverage = leverage
        self.slippage_pct = slippage_pct
        self.brokerage_per_order = brokerage_per_order

    def run(self, df: pd.DataFrame, symbol: str) -> BacktestResult:
        """Run backtest on a single symbol's OHLCV DataFrame."""
        capital = self.initial_capital
        peak_capital = capital
        max_dd = 0.0
        max_dd_pct = 0.0
        equity_curve: List[float] = [capital]
        trade_logs: List[Dict[str, Any]] = []

        open_position: Optional[Position] = None
        consecutive_wins = 0
        consecutive_losses = 0
        max_consecutive_wins = 0
        max_consecutive_losses = 0

        # Feed data candle by candle
        for i in range(len(df)):
            candle = df.iloc[i].to_dict()
            curr_price = float(candle["close"])
            high_price = float(candle["high"])
            low_price = float(candle["low"])
            timestamp = candle.get("timestamp", datetime.now())

            # Update strategy internal state
            self.strategy.update_data(symbol, candle)

            # 1. Manage Open Position if active
            if open_position is not None:
                is_long = open_position.side == OrderSide.BUY
                exit_price: Optional[float] = None
                exit_reason = ""

                target = open_position.target
                stop = open_position.stop_loss

                if is_long:
                    if target > 0 and high_price >= target:
                        exit_price = target * (1.0 - self.slippage_pct / 100.0)
                        exit_reason = "Target Hit"
                    elif stop > 0 and low_price <= stop:
                        exit_price = stop * (1.0 - self.slippage_pct / 100.0)
                        exit_reason = "Stop Loss Hit"
                else:
                    if target > 0 and low_price <= target:
                        exit_price = target * (1.0 + self.slippage_pct / 100.0)
                        exit_reason = "Target Hit"
                    elif stop > 0 and high_price >= stop:
                        exit_price = stop * (1.0 + self.slippage_pct / 100.0)
                        exit_reason = "Stop Loss Hit"

                # Check strategy exit logic (trailing stop / time-based exit at 15:10)
                if exit_price is None:
                    market_snapshot = {"symbol": symbol, "ltp": curr_price, "timestamp": timestamp}
                    if self.strategy.should_exit(open_position, market_snapshot):
                        exit_price = curr_price * (1.0 - self.slippage_pct / 100.0 if is_long else 1.0 + self.slippage_pct / 100.0)
                        exit_reason = "Strategy Exit"

                # If position closed
                if exit_price is not None:
                    multiplier = 1 if is_long else -1
                    gross_pnl = (exit_price - open_position.entry_price) * open_position.quantity * multiplier
                    net_pnl = gross_pnl - (self.brokerage_per_order * 2)  # Entry + Exit brokerage
                    capital += net_pnl

                    pnl_pct = (net_pnl / (open_position.entry_price * open_position.quantity)) * 100

                    if net_pnl > 0:
                        consecutive_wins += 1
                        consecutive_losses = 0
                        max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
                    else:
                        consecutive_losses += 1
                        consecutive_wins = 0
                        max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)

                    trade_logs.append({
                        "trade_id": len(trade_logs) + 1,
                        "symbol": symbol,
                        "side": open_position.side.value,
                        "entry_time": open_position.entry_time,
                        "exit_time": timestamp,
                        "entry_price": round(open_position.entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "quantity": open_position.quantity,
                        "net_pnl": round(net_pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "reason": exit_reason,
                    })

                    open_position = None

            # Track Drawdown & Equity
            peak_capital = max(peak_capital, capital)
            dd = peak_capital - capital
            dd_pct = (dd / peak_capital) * 100 if peak_capital > 0 else 0.0
            max_dd = max(max_dd, dd)
            max_dd_pct = max(max_dd_pct, dd_pct)
            equity_curve.append(capital)

            # 2. Seek New Entry if no position
            if open_position is None:
                market_snapshot = {"symbol": symbol, "ltp": curr_price, "timestamp": timestamp}
                signal: Optional[Signal] = self.strategy.analyze(market_snapshot)

                if signal and signal.signal_type in (SignalType.BUY, SignalType.SELL):
                    side = OrderSide.BUY if signal.signal_type == SignalType.BUY else OrderSide.SELL
                    entry_price = curr_price * (1.0 + self.slippage_pct / 100.0 if side == OrderSide.BUY else 1.0 - self.slippage_pct / 100.0)

                    # Extract target and stop loss from signal metadata or fallback
                    meta = signal.metadata or {}
                    stop_loss = meta.get("calculated_stop_loss", 0.0)
                    target = meta.get("calculated_target", 0.0)

                    if stop_loss == 0.0:
                        stop_loss = entry_price * 0.985 if side == OrderSide.BUY else entry_price * 1.015
                    if target == 0.0:
                        target = entry_price * 1.018 if side == OrderSide.BUY else entry_price * 0.982

                    # Calculate position size
                    risk_amount = capital * (self.risk_per_trade_pct / 100.0)
                    risk_per_share = abs(entry_price - stop_loss)
                    qty = int(risk_amount / risk_per_share) if risk_per_share > 0 else 1
                    max_affordable = int((capital * self.leverage) / entry_price) if entry_price > 0 else 1
                    qty = max(1, min(qty, max_affordable))

                    open_position = Position(
                        symbol=symbol,
                        side=side,
                        quantity=qty,
                        entry_price=entry_price,
                        current_price=entry_price,
                        stop_loss=stop_loss,
                        target=target,
                        entry_time=timestamp if isinstance(timestamp, datetime) else datetime.now(),
                    )

        # Close open position at end
        if open_position is not None:
            last_close = float(df.iloc[-1]["close"])
            is_long = open_position.side == OrderSide.BUY
            multiplier = 1 if is_long else -1
            gross_pnl = (last_close - open_position.entry_price) * open_position.quantity * multiplier
            net_pnl = gross_pnl - (self.brokerage_per_order * 2)
            capital += net_pnl
            trade_logs.append({
                "trade_id": len(trade_logs) + 1,
                "symbol": symbol,
                "side": open_position.side.value,
                "entry_time": open_position.entry_time,
                "exit_time": df.iloc[-1]["timestamp"],
                "entry_price": round(open_position.entry_price, 2),
                "exit_price": round(last_close, 2),
                "quantity": open_position.quantity,
                "net_pnl": round(net_pnl, 2),
                "pnl_pct": round((net_pnl / (open_position.entry_price * open_position.quantity)) * 100, 2),
                "reason": "End of Data Square-off",
            })
            equity_curve.append(capital)

        # Performance Metrics Computation
        total_trades = len(trade_logs)
        pnls = [t["net_pnl"] for t in trade_logs]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        winning_trades = len(wins)
        losing_trades = len(losses)
        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)

        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(abs(np.mean(losses))) if losses else 0.0
        win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

        win_prob = win_rate / 100.0
        loss_prob = 1.0 - win_prob
        expectancy = (win_prob * avg_win) - (loss_prob * avg_loss)

        returns = pd.Series(pnls) / self.initial_capital
        sharpe_ratio = float((returns.mean() / returns.std()) * np.sqrt(252)) if len(returns) > 1 and returns.std() > 0 else 0.0

        best_trade = max(pnls) if pnls else 0.0
        worst_trade = min(pnls) if pnls else 0.0

        return BacktestResult(
            strategy_name=self.strategy.name,
            symbol=symbol,
            initial_capital=self.initial_capital,
            final_capital=round(capital, 2),
            total_pnl=round(capital - self.initial_capital, 2),
            pnl_pct=round(((capital - self.initial_capital) / self.initial_capital) * 100.0, 2),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=round(win_rate, 2),
            profit_factor=round(profit_factor, 2),
            sharpe_ratio=round(sharpe_ratio, 2),
            max_drawdown=round(max_dd, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            win_loss_ratio=round(win_loss_ratio, 2),
            expectancy=round(expectancy, 2),
            best_trade=round(best_trade, 2),
            worst_trade=round(worst_trade, 2),
            max_consecutive_wins=max_consecutive_wins,
            max_consecutive_losses=max_consecutive_losses,
            trade_logs=trade_logs,
            equity_curve=equity_curve,
        )

    def generate_report(self, res: BacktestResult) -> str:
        """Format backtest results into an executive summary report."""
        status_icon = "[TARGET ACHIEVED (>= 70%)]" if res.win_rate >= 70.0 else "[BELOW 70%]"
        lines = [
            "=" * 68,
            f"          BACKTEST REPORT -- {res.strategy_name.upper()}",
            f"          Instrument: {res.symbol} | Result: {status_icon}",
            "=" * 68,
            f"  Initial Capital  : Rs. {res.initial_capital:,.2f}",
            f"  Final Capital    : Rs. {res.final_capital:,.2f}",
            f"  Total Net Profit : Rs. {res.total_pnl:,.2f} ({res.pnl_pct:+.2f}%)",
            "-" * 68,
            f"  Total Trades     : {res.total_trades}",
            f"  Winning Trades   : {res.winning_trades} ({res.win_rate:.2f}%)",
            f"  Losing Trades    : {res.losing_trades} ({100.0 - res.win_rate:.2f}%)",
            f"  Win / Loss Ratio : {res.win_loss_ratio:.2f} : 1.0",
            "-" * 68,
            f"  Profit Factor    : {res.profit_factor:.2f}",
            f"  Expectancy       : Rs. {res.expectancy:,.2f} / trade",
            f"  Sharpe Ratio     : {res.sharpe_ratio:.2f}",
            f"  Max Drawdown     : Rs. {res.max_drawdown:,.2f} ({res.max_drawdown_pct:.2f}%)",
            "-" * 68,
            f"  Average Win      : Rs. {res.avg_win:,.2f}",
            f"  Average Loss     : Rs. {res.avg_loss:,.2f}",
            f"  Best Trade       : Rs. {res.best_trade:,.2f}",
            f"  Worst Trade      : Rs. {res.worst_trade:,.2f}",
            f"  Max Win Streak   : {res.max_consecutive_wins} trades",
            f"  Max Loss Streak  : {res.max_consecutive_losses} trades",
            "=" * 68,
        ]
        return "\n".join(lines)

    @staticmethod
    def generate_sample_data(
        symbol: str = "RELIANCE",
        days: int = 45,
        base_price: float = 2850.0,
        seed: int = 42,
    ) -> pd.DataFrame:
        """Generates realistic 5-minute intraday NSE candles (09:15 to 15:30)."""
        np.random.seed(seed)
        start_date = datetime.now() - timedelta(days=days * 1.5)
        candles: List[Dict[str, Any]] = []

        curr_price = base_price
        curr_day = start_date
        completed_days = 0

        while completed_days < days:
            # Skip Saturday and Sunday
            if curr_day.weekday() >= 5:
                curr_day += timedelta(days=1)
                continue

            day_open = curr_price * (1.0 + np.random.normal(0.001, 0.004))
            curr_price = day_open

            # Generate 75 5-min candles per trading day (09:15 to 15:30)
            day_trend = np.random.choice([1, -1], p=[0.55, 0.45])  # slight upward bias
            trend_drift = day_trend * np.random.uniform(0.0001, 0.0005)

            for candle_idx in range(75):
                ts = datetime(
                    curr_day.year,
                    curr_day.month,
                    curr_day.day,
                    9,
                    15,
                ) + timedelta(minutes=candle_idx * 5)

                # U-shaped intraday volume profile
                time_weight = 1.8 if (candle_idx < 12 or candle_idx > 65) else 0.7
                base_vol = int(np.random.gamma(shape=3.0, scale=4000.0) * time_weight)

                # Volatility and price movement
                shock = np.random.normal(trend_drift, 0.0018)
                o = curr_price
                c = o * (1.0 + shock)
                h = max(o, c) * (1.0 + abs(np.random.normal(0, 0.0012)))
                l = min(o, c) * (1.0 - abs(np.random.normal(0, 0.0012)))

                candles.append({
                    "timestamp": ts,
                    "open": round(o, 2),
                    "high": round(h, 2),
                    "low": round(l, 2),
                    "close": round(c, 2),
                    "volume": max(100, base_vol),
                })
                curr_price = c

            completed_days += 1
            curr_day += timedelta(days=1)

        return pd.DataFrame(candles)
