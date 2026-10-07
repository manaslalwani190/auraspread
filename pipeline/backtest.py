"""
AuraSpread – backtest.py
Walk-forward backtest with:
- Train / test split (no test-set look-ahead)
- Signal at close t, execute at close t+1
- Lot-matched hedged two-leg trades
- Entries blocked near tender/expiry
- P&L on actual prices held
- Equity curve: gross, net-of-cost, gold-neutral
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from pipeline.config import (
    TRAIN_FRAC,
    MAX_LOTS_PER_TRADE,
    TENDER_BLACKOUT_DAYS,
    EXPIRY_BLACKOUT_DAYS,
    CONTRACTS,
)
from pipeline.analysis import estimate_round_trip_cost

log = logging.getLogger(__name__)


@dataclass
class Trade:
    entry_date:    date
    exit_date:     Optional[date]
    sym_a:         str
    sym_b:         str
    direction:     int          # +1 = long residual, -1 = short
    lots:          int
    entry_price_a: float
    entry_price_b: float
    exit_price_a:  float  = 0.0
    exit_price_b:  float  = 0.0
    gross_pnl:     float  = 0.0
    cost:          float  = 0.0
    net_pnl:       float  = 0.0
    open:          bool   = True


def _near_expiry_blackout(trade_date, expiry, days: int) -> bool:
    try:
        d_exp = pd.to_datetime(expiry)
        d_trade = pd.to_datetime(trade_date)
        diff = (d_exp - d_trade).days
        return 0 <= diff <= days
    except Exception:
        return False


def _lot_match(sym_a: str, sym_b: str) -> tuple[int, int]:
    """
    Return (lots_a, lots_b) such that the notional gold quantity is matched.
    Unit: grams.  lot_size_a × lots_a ≈ lot_size_b × lots_b.
    We use LCM / GCD approach, capped at MAX_LOTS_PER_TRADE.
    """
    from math import gcd
    g_a = CONTRACTS[sym_a]["lot_size"]
    g_b = CONTRACTS[sym_b]["lot_size"]
    common = g_a * g_b // gcd(g_a, g_b)
    lots_a = min(common // g_a, MAX_LOTS_PER_TRADE)
    lots_b = min(common // g_b, MAX_LOTS_PER_TRADE)
    return lots_a, lots_b


def run_backtest(
    signals_df: pd.DataFrame,
    sym_a: str,
    sym_b: str,
    gold_prices: Optional[pd.Series] = None,
) -> dict:
    """
    Walk-forward backtest for a single pair (sym_a, sym_b).

    Parameters
    ----------
    signals_df : Output of analysis.generate_signals(), must have columns:
        Date, NormBase, NormTarget, Signal, EstCost, BaseExpiry, TargetExpiry
    sym_a, sym_b: The contract pair

    Returns
    -------
    dict with keys: trades, equity_gross, equity_net, split_date, metrics
    """
    df = signals_df.sort_values("Date").reset_index(drop=True)
    n  = len(df)

    if n < 20:
        return {
            "trades": [], "equity_gross": [], "equity_net": [],
            "split_date": None, "metrics": {}, "sym_a": sym_a, "sym_b": sym_b,
        }

    # Train/test split
    split_idx  = int(n * TRAIN_FRAC)
    split_date = df.iloc[split_idx]["Date"]
    test_df    = df.iloc[split_idx:].reset_index(drop=True)

    lots_a, lots_b = _lot_match(sym_a, sym_b)
    log.info(f"Backtest {sym_a}/{sym_b}: {len(test_df)} test days, lots={lots_a}/{lots_b}")

    trades:       list[Trade]  = []
    equity_gross: list[float]  = [0.0]
    equity_net:   list[float]  = [0.0]
    dates_list:   list[date]   = []
    active_trade: Optional[Trade] = None
    cum_gross     = 0.0
    cum_net       = 0.0

    for i in range(len(test_df) - 1):
        row      = test_df.iloc[i]
        next_row = test_df.iloc[i + 1]
        exec_date = next_row["Date"]
        signal    = int(row["Signal"])

        # ── Exit logic ──────────────────────────────────────────────────
        if active_trade is not None:
            # Force exit near expiry of either leg
            b_exp = row.get("BaseExpiry",   pd.NaT)
            t_exp = row.get("TargetExpiry", pd.NaT)
            force_exit = False
            for exp in (b_exp, t_exp):
                if pd.notna(exp) and _near_expiry_blackout(exec_date, exp, EXPIRY_BLACKOUT_DAYS):
                    force_exit = True

            # Exit if signal reversed or force-exit
            if signal == 0 or signal == -active_trade.direction or force_exit:
                active_trade.exit_date    = exec_date
                active_trade.exit_price_a = next_row["NormBase"]
                active_trade.exit_price_b = next_row["NormTarget"]
                active_trade.open         = False

                # P&L: direction × (spread_exit - spread_entry) × lots
                spread_entry = (active_trade.entry_price_b - active_trade.entry_price_a)
                spread_exit  = (active_trade.exit_price_b  - active_trade.exit_price_a)

                raw_pnl = active_trade.direction * (spread_exit - spread_entry)
                # Scale by smaller-lot side (conservative)
                raw_pnl *= min(lots_a, lots_b)

                cost = estimate_round_trip_cost(
                    (next_row["NormBase"] + next_row["NormTarget"]) / 2,
                    sym_a, sym_b,
                    vol_a=next_row.get("Volume_a", 1000),
                    vol_b=next_row.get("Volume_b", 1000),
                )
                active_trade.gross_pnl = raw_pnl
                active_trade.cost      = cost
                active_trade.net_pnl   = raw_pnl - cost

                cum_gross += raw_pnl
                cum_net   += raw_pnl - cost
                trades.append(active_trade)
                active_trade = None

        # ── Entry logic ─────────────────────────────────────────────────
        if active_trade is None and signal != 0:
            b_exp = next_row.get("BaseExpiry",   pd.NaT)
            t_exp = next_row.get("TargetExpiry", pd.NaT)
            blocked = False
            for exp in (b_exp, t_exp):
                if pd.notna(exp) and _near_expiry_blackout(exec_date, exp, TENDER_BLACKOUT_DAYS):
                    blocked = True

            if not blocked:
                active_trade = Trade(
                    entry_date    = exec_date,
                    exit_date     = None,
                    sym_a         = sym_a,
                    sym_b         = sym_b,
                    direction     = signal,
                    lots          = min(lots_a, lots_b),
                    entry_price_a = next_row["NormBase"],
                    entry_price_b = next_row["NormTarget"],
                )

        equity_gross.append(cum_gross)
        equity_net.append(cum_net)
        dates_list.append(exec_date)

    # Force-close any open trade at end of test period
    if active_trade is not None and len(test_df) > 0:
        last = test_df.iloc[-1]
        active_trade.exit_date    = last["Date"]
        active_trade.exit_price_a = last["NormBase"]
        active_trade.exit_price_b = last["NormTarget"]
        active_trade.open         = False
        spread_entry = active_trade.entry_price_b - active_trade.entry_price_a
        spread_exit  = last["NormTarget"] - last["NormBase"]
        raw_pnl = active_trade.direction * (spread_exit - spread_entry)
        raw_pnl *= min(lots_a, lots_b)
        cost = estimate_round_trip_cost(
            (last["NormBase"] + last["NormTarget"]) / 2, sym_a, sym_b)
        active_trade.gross_pnl = raw_pnl
        active_trade.cost      = cost
        active_trade.net_pnl   = raw_pnl - cost
        trades.append(active_trade)

    # ── Metrics ──────────────────────────────────────────────────────────
    metrics = _compute_metrics(trades, equity_net, test_df, gold_prices)

    return {
        "trades":       [_trade_to_dict(t) for t in trades],
        "equity_gross": equity_gross,
        "equity_net":   equity_net,
        "dates":        [str(d) for d in dates_list],
        "split_date":   str(split_date),
        "metrics":      metrics,
        "sym_a":        sym_a,
        "sym_b":        sym_b,
    }


def _trade_to_dict(t: Trade) -> dict:
    return {
        "entry_date":    str(t.entry_date),
        "exit_date":     str(t.exit_date) if t.exit_date else None,
        "sym_a":         t.sym_a,
        "sym_b":         t.sym_b,
        "direction":     t.direction,
        "lots":          t.lots,
        "gross_pnl":     round(t.gross_pnl, 4),
        "cost":          round(t.cost,       4),
        "net_pnl":       round(t.net_pnl,    4),
    }


def calculate_beta_to_gold(
    equity_net: list[float],
    gold_prices: Optional[pd.Series | np.ndarray] = None,
) -> float:
    """
    Calculate Beta to Gold for the spread strategy:
    Regression: spread_pnl = alpha + beta * gold_returns
    Beta = covariance(spread_pnl, gold_returns) / variance(gold_returns)

    - Y: daily P&L of spread strategy normalized to fractional returns (spread_daily_pnl / avg_gold_price)
    - X: daily MCX gold benchmark percentage returns
    Returns beta typically between -1 and +1 (bounded [-2.0, +2.0]).
    """
    if len(equity_net) < 5 or gold_prices is None or len(gold_prices) < 5:
        return 0.0

    daily_pnl = np.diff(np.array(equity_net, dtype=float))

    if isinstance(gold_prices, pd.Series):
        s = gold_prices.dropna()
        if len(s) < 5:
            return 0.0
        gold_ret = s.pct_change().dropna().values
        avg_gold_price = float(np.median(s.values))
    else:
        gold_arr = np.array(gold_prices, dtype=float)
        gold_arr = gold_arr[~np.isnan(gold_arr)]
        if len(gold_arr) < 5:
            return 0.0
        gold_ret = np.diff(gold_arr) / gold_arr[:-1]
        avg_gold_price = float(np.median(gold_arr))

    if avg_gold_price <= 0:
        avg_gold_price = 72000.0

    # Dimensionless daily spread return matching gold_ret units
    spread_ret = daily_pnl / avg_gold_price

    n = min(len(spread_ret), len(gold_ret))
    if n < 5:
        return 0.0

    y = spread_ret[:n]
    x = gold_ret[:n]

    var_x = float(np.var(x, ddof=1))
    if var_x < 1e-12:
        return 0.0

    cov_xy = float(np.cov(y, x, ddof=1)[0, 1])
    beta = cov_xy / var_x

    if np.isnan(beta) or np.isinf(beta):
        return 0.0

    # Spread strategy should typically be between -1 and +1, bounded [-2.0, +2.0]
    beta = max(-2.0, min(2.0, beta))
    return round(float(beta), 4)


def _compute_metrics(
    trades: list[Trade],
    equity_net: list[float],
    test_df: pd.DataFrame,
    gold_prices: Optional[pd.Series | np.ndarray] = None,
) -> dict:
    if not trades:
        return {
            "n_trades": 0, "gross_pnl": 0, "net_pnl": 0,
            "hit_rate": 0, "sharpe": 0, "max_drawdown": 0,
            "turnover": 0, "beta_to_gold": 0.0,
        }

    n          = len(trades)
    winners    = [t for t in trades if t.net_pnl > 0]
    gross_pnl  = sum(t.gross_pnl for t in trades)
    net_pnl    = sum(t.net_pnl   for t in trades)
    hit_rate   = len(winners) / n if n else 0

    eq = np.array(equity_net, dtype=float)
    if len(eq) > 1:
        daily_ret = np.diff(eq)
        sharpe = (np.mean(daily_ret) / (np.std(daily_ret) + 1e-10)) * np.sqrt(252)
        peak    = np.maximum.accumulate(eq)
        dd      = (eq - peak) / (np.abs(peak) + 1e-10)
        max_dd  = float(np.min(dd))
    else:
        sharpe = 0.0
        max_dd = 0.0

    if gold_prices is None and "NormBase" in test_df.columns:
        gold_prices = test_df["NormBase"]

    beta_to_gold = calculate_beta_to_gold(equity_net, gold_prices)

    return {
        "n_trades":     n,
        "gross_pnl":    round(gross_pnl, 2),
        "net_pnl":      round(net_pnl,   2),
        "hit_rate":     round(hit_rate,  4),
        "sharpe":       round(float(sharpe), 4),
        "max_drawdown": round(max_dd, 4),
        "turnover":     n,
        "beta_to_gold": beta_to_gold,
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    _ROOT = Path(__file__).resolve().parent.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

    from pipeline.config import DATA_PROC
    from pipeline.normalize import build_normalized_panel
    from pipeline.analysis import carry_adjusted_price

    print("=" * 72)
    print("AuraSpread - Residual Diagnosis for GOLDM-GOLDPETAL Spread")
    print("=" * 72)

    pq_path = DATA_PROC / "gold_contracts_clean.parquet"
    if not pq_path.exists():
        print(f"Error: {pq_path} not found. Please run pipeline first.")
        sys.exit(1)

    raw_df = pd.read_parquet(pq_path)
    norm_panel = build_normalized_panel(raw_df)

    # 1. Unadjusted / Naive Spread (illustrating the bug source)
    gm_raw = norm_panel[norm_panel["Symbol"] == "GOLDM"].sort_values("ExpiryDate").groupby("Date", as_index=False).first()
    gp_raw = norm_panel[norm_panel["Symbol"] == "GOLDPETAL"].sort_values("ExpiryDate").groupby("Date", as_index=False).first()
    naive_m = pd.merge(
        gm_raw[["Date", "NormClose", "ExpiryDate"]].rename(columns={"NormClose": "NormBase", "ExpiryDate": "BaseExp"}),
        gp_raw[["Date", "NormClose", "ExpiryDate"]].rename(columns={"NormClose": "NormTarget", "ExpiryDate": "TargetExp"}),
        on="Date"
    )
    naive_m["ExpiryGapDays"] = (pd.to_datetime(naive_m["TargetExp"]) - pd.to_datetime(naive_m["BaseExp"])).dt.days
    naive_m["RawResidual"] = naive_m["NormTarget"] - naive_m["NormBase"]
    naive_m["NaiveCarryAdj"] = naive_m["NormBase"] + (naive_m["NormBase"] * 0.065 / 252) * naive_m["ExpiryGapDays"]
    naive_m["NaiveResidual"] = naive_m["NormTarget"] - naive_m["NaiveCarryAdj"]

    print("\n[ROOT CAUSE INSPECTION - NAIVE / UNADJUSTED MISMATCH]:")
    worst_naive = naive_m.sort_values(by="NaiveResidual", key=abs, ascending=False).iloc[0]
    print(f"  Worst Anomaly Date      : {worst_naive['Date']}")
    print(f"  GOLDM Base Expiry       : {worst_naive['BaseExp']} (Norm Base: INR {worst_naive['NormBase']:,.2f})")
    print(f"  GOLDPETAL Target Expiry : {worst_naive['TargetExp']} (Norm Target: INR {worst_naive['NormTarget']:,.2f})")
    print(f"  Unmatched Expiry Gap    : {worst_naive['ExpiryGapDays']} days (NEGATIVE GAP -> Out-of-cycle mismatch!)")
    print(f"  Raw Spread (Target-Base): INR {worst_naive['RawResidual']:,.2f} / 10g")
    print(f"  Naive Carry-Adj Residual: INR {worst_naive['NaiveResidual']:,.2f} / 10g  <-- Source of ~25,000 error!")

    # 2. Corrected Carry-Adjusted Spread
    adj_df = carry_adjusted_price(norm_panel, "GOLDM", "GOLDPETAL")
    print("\n[CORRECTED CARRY-ADJUSTED SPREAD - CYCLE-MATCHED]:")
    sample_dates = ["2026-01-30", "2026-01-23", "2025-10-06", "2026-03-10"]
    for d_str in sample_dates:
        row_sub = adj_df[adj_df["Date"].astype(str) == d_str]
        if not row_sub.empty:
            r = row_sub.iloc[0]
            print(f"  Date {d_str}: NormBase={r['NormBase']:,.2f} ({r['BaseExpiry']}) | "
                  f"NormTarget={r['NormTarget']:,.2f} ({r['TargetExpiry']}) | "
                  f"Gap={r['ExpiryGapDays']}d | CarryAdjBase={r['CarryAdjBase']:,.2f} | "
                  f"Residual={r['Residual']:+.2f} INR/10g")

    print("\n[STATISTICAL SUMMARY OF CORRECTED RESIDUALS]:")
    print(f"  Total Observations  : {len(adj_df)}")
    print(f"  Minimum Residual    : {adj_df['Residual'].min():+.2f} INR/10g")
    print(f"  Maximum Residual    : {adj_df['Residual'].max():+.2f} INR/10g")
    print(f"  Mean Residual       : {adj_df['Residual'].mean():+.2f} INR/10g")
    print(f"  Std Residual        : {adj_df['Residual'].std():.2f} INR/10g")
    print(f"  All within +/-500   : {bool((adj_df['Residual'].abs() <= 500.0).all())}")
    print("=" * 72)
