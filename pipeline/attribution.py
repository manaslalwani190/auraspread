"""
AuraSpread – attribution.py
Regression of strategy returns on gold returns for P&L attribution.
Reports: beta, gross P&L, net-of-cost P&L, gold-neutral P&L.
Also: breakeven analysis per pair.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def attribute_returns(
    equity_net: list[float],
    gold_prices: Optional[pd.Series] = None,
) -> dict:
    """
    Regress strategy daily P&L on gold daily returns.

    Parameters
    ----------
    equity_net  : Cumulative net P&L series (list of floats)
    gold_prices : Gold price series (NormClose of GOLDM or GOLDTEN near-month)
                  indexed by integer position matching equity_net.

    Returns
    -------
    dict: beta, alpha, r_squared, gold_neutral_pnl, explained_pnl
    """
    if len(equity_net) < 5:
        return {"beta": 0.0, "alpha": 0.0, "r_squared": 0.0,
                "gold_neutral_pnl": 0.0, "explained_pnl": 0.0}

    strategy_returns = np.diff(equity_net)

    if gold_prices is None or len(gold_prices) < len(strategy_returns):
        # No gold series available → beta = 0
        return {
            "beta":             0.0,
            "alpha":            float(np.mean(strategy_returns)),
            "r_squared":        0.0,
            "gold_neutral_pnl": float(np.sum(strategy_returns)),
            "explained_pnl":    0.0,
        }

    gold_ret = gold_prices.pct_change().dropna().values
    n = min(len(strategy_returns), len(gold_ret))
    if n < 5:
        return {"beta": 0.0, "alpha": 0.0, "r_squared": 0.0,
                "gold_neutral_pnl": 0.0, "explained_pnl": 0.0}

    # Convert strategy P&L (₹ absolute) to fractional returns so units match
    # gold_ret (which is pct_change, e.g. 0.001).  Use median gold price as
    # the normalising constant so extreme days don't distort the regression.
    avg_gold_price = float(np.median(gold_prices.values))
    if avg_gold_price < 1:
        avg_gold_price = 72000.0
    y = strategy_returns[:n] / avg_gold_price
    x = gold_ret[:n]

    # OLS via numpy
    X = np.column_stack([np.ones(n), x])
    try:
        coeffs, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
        alpha_hat, beta_hat = coeffs
    except np.linalg.LinAlgError:
        beta_hat = alpha_hat = 0.0

    y_pred    = alpha_hat + beta_hat * x
    ss_res    = np.sum((y - y_pred) ** 2)
    ss_tot    = np.sum((y - np.mean(y)) ** 2)
    r_sq      = 1 - ss_res / (ss_tot + 1e-12)

    explained_pnl    = float(np.sum(beta_hat * x)) * avg_gold_price
    gold_neutral_pnl = float(np.sum(strategy_returns[:n])) - explained_pnl

    beta_hat = max(-2.0, min(2.0, float(beta_hat)))

    return {
        "beta":             round(float(beta_hat),      4),
        "alpha":            round(float(alpha_hat),     4),
        "r_squared":        round(float(r_sq),          4),
        "gold_neutral_pnl": round(gold_neutral_pnl,    2),
        "explained_pnl":    round(explained_pnl,        2),
    }


def compute_breakeven(
    trades: list[dict],
    estimated_cost: float,
) -> dict:
    """
    Compute the maximum round-trip cost at which the strategy stays profitable.

    breakeven_cost = gross_pnl / n_trades
    edge_survives  = breakeven_cost > estimated_cost

    Returns dict: breakeven_cost, estimated_cost, edge_survives, margin
    """
    if not trades:
        return {
            "breakeven_cost": 0.0,
            "estimated_cost": estimated_cost,
            "edge_survives":  False,
            "margin":         -estimated_cost,
        }

    gross_pnl = sum(t["gross_pnl"] for t in trades)
    n         = len(trades)
    be_cost   = gross_pnl / n if n > 0 else 0.0
    margin    = be_cost - estimated_cost

    return {
        "breakeven_cost": round(be_cost,          2),
        "estimated_cost": round(estimated_cost,   2),
        "edge_survives":  bool(margin > 0),
        "margin":         round(margin,            2),
    }


def build_gold_neutral_equity(
    equity_net: list[float],
    gold_prices: Optional[pd.Series],
    beta: float,
) -> list[float]:
    """
    Return a gold-neutral equity curve by subtracting the beta-weighted
    gold return component from each daily P&L step.
    """
    if len(equity_net) < 2:
        return equity_net

    strategy_returns = np.diff(equity_net)

    if gold_prices is None or len(gold_prices) < len(strategy_returns) or abs(beta) < 1e-6:
        return equity_net

    gold_ret = gold_prices.pct_change().dropna().values
    n = min(len(strategy_returns), len(gold_ret))

    avg_gold_price = float(np.median(gold_prices.values))
    if avg_gold_price < 1:
        avg_gold_price = 72000.0

    hedged = strategy_returns[:n] - (beta * avg_gold_price) * gold_ret[:n]
    cumulative = np.concatenate([[0.0], np.cumsum(hedged)])
    return [round(float(v), 4) for v in cumulative]
