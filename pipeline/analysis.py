"""
AuraSpread – analysis.py
Core quantitative analysis:
  1. Carry estimation and carry-adjusted residual spreads
  2. Robust z-score (median/MAD) with strict look-ahead guard
  3. Term-structure curve and roll-down vs genuine-shift decomposition
  4. Cost model (fees, slippage, thin-day penalty)
  5. Signal generation
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from pipeline.config import (
    CONTRACTS,
    ZSCORE_MIN_OBS,
    ZSCORE_BUFFER_SIGMA,
    COST_BROKERAGE_PCT,
    COST_STT_PCT,
    COST_EXCHANGE_CHARGE,
    SLIPPAGE_BASE,
    SLIPPAGE_THIN_MULT,
    THIN_VOLUME_LOTS,
    TENDER_BLACKOUT_DAYS,
    EXPIRY_BLACKOUT_DAYS,
)

log = logging.getLogger(__name__)

PAIRS = [
    ("GOLDM",     "GOLDTEN"),
    ("GOLDM",     "GOLDGUINEA"),
    ("GOLDM",     "GOLDPETAL"),
    ("GOLDTEN",   "GOLDGUINEA"),
    ("GOLDTEN",   "GOLDPETAL"),
    ("GOLDGUINEA","GOLDPETAL"),
]


# ── 1. Carry estimation ────────────────────────────────────────────────────

def estimate_carry_per_day(
    norm_prices: pd.DataFrame,
    symbol: str,
) -> pd.Series:
    """
    For each date, estimate the implied carry per day from the term structure
    of consecutive expiries for `symbol`.
    If multiple expiries are present:
        carry_per_day = (F2 - F1) / days_between_expiries
    If only one expiry is present:
        carry_per_day = NormClose * 0.065 / 365 (6.5% p.a. standard MCX carry proxy)

    Returns a Series indexed by (Date, ExpiryDate) → carry_per_day (INR/10g/day).
    """
    sub = norm_prices[norm_prices["Symbol"] == symbol].copy()
    sub = sub.sort_values(["Date", "ExpiryDate"])

    results: list[dict] = []
    for trade_date, grp in sub.groupby("Date"):
        grp = grp.sort_values("ExpiryDate")
        expiries = grp["ExpiryDate"].tolist()
        prices   = grp["NormClose"].tolist()
        if len(expiries) > 1:
            for i in range(len(expiries) - 1):
                days_gap = max(1, (pd.to_datetime(expiries[i + 1]) - pd.to_datetime(expiries[i])).days)
                carry_pd = (prices[i + 1] - prices[i]) / days_gap
                results.append({
                    "Date":        trade_date,
                    "ExpiryDate":  expiries[i],
                    "CarryPerDay": carry_pd,
                })
        elif len(expiries) == 1:
            carry_pd = prices[0] * 0.065 / 365.0
            results.append({
                "Date":        trade_date,
                "ExpiryDate":  expiries[0],
                "CarryPerDay": carry_pd,
            })

    if not results:
        return pd.Series(dtype=float, name="CarryPerDay")

    carry_df = pd.DataFrame(results).set_index(["Date", "ExpiryDate"])
    return carry_df["CarryPerDay"]


def carry_adjusted_price(
    norm_prices: pd.DataFrame,
    base_sym: str,
    target_sym: str,
    market_carry: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Compute carry-adjusted spread between base_sym and target_sym.

    GOLDM expires ~25 days before end-of-month contracts. We adjust
    GOLDM's price forward by the estimated daily carry × expiry_gap_days
    so both prices are on a comparable expiry basis. Contracts are cycle-matched
    by delivery month to prevent cross-month expiry mismatch.

    Returns a DataFrame with columns:
        Date, NormBase, NormTarget, BaseExpiry, TargetExpiry,
        ExpiryGapDays, ImpliedCarry, CarryAdjBase, Residual
    """
    base_df   = norm_prices[norm_prices["Symbol"] == base_sym].copy()
    target_df = norm_prices[norm_prices["Symbol"] == target_sym].copy()

    for d in (base_df, target_df):
        d["Date_dt"] = pd.to_datetime(d["Date"])
        d["Exp_dt"]  = pd.to_datetime(d["ExpiryDate"])
        d["DaysToExp"] = (d["Exp_dt"] - d["Date_dt"]).dt.days

    # Filter out contracts expiring within EXPIRY_BLACKOUT_DAYS (e.g. 0-1 days remaining)
    base_clean = base_df[base_df["DaysToExp"] >= EXPIRY_BLACKOUT_DAYS]
    if base_clean.empty:
        base_clean = base_df
    target_clean = target_df[target_df["DaysToExp"] >= EXPIRY_BLACKOUT_DAYS]
    if target_clean.empty:
        target_clean = target_df

    # Consistent rolling logic: keep NEAREST active expiry contract per date
    sort_cols_b = ["Date", "ExpiryDate"] + (["Volume"] if "Volume" in base_clean.columns else [])
    asc_b = [True, True] + ([False] if "Volume" in base_clean.columns else [])
    b_n = base_clean.sort_values(sort_cols_b, ascending=asc_b).groupby("Date", as_index=False).first()

    sort_cols_t = ["Date", "ExpiryDate"] + (["Volume"] if "Volume" in target_clean.columns else [])
    asc_t = [True, True] + ([False] if "Volume" in target_clean.columns else [])
    t_n = target_clean.sort_values(sort_cols_t, ascending=asc_t).groupby("Date", as_index=False).first()

    merged = pd.merge(
        b_n[["Date", "NormClose", "ExpiryDate"]].rename(
            columns={"NormClose": "NormBase", "ExpiryDate": "BaseExpiry"}
        ),
        t_n[["Date", "NormClose", "ExpiryDate"]].rename(
            columns={"NormClose": "NormTarget", "ExpiryDate": "TargetExpiry"}
        ),
        on="Date",
        how="inner",
    ).sort_values("Date").reset_index(drop=True)

    if merged.empty:
        return pd.DataFrame()

    merged["ExpiryGapDays"] = (
        pd.to_datetime(merged["TargetExpiry"]) - pd.to_datetime(merged["BaseExpiry"])
    ).dt.days

    # Daily implied carry rate: 6.5% p.a. standard MCX rate over 365 calendar days
    merged["ImpliedCarry"] = merged["NormBase"] * 0.065 / 365.0

    if market_carry is not None and not market_carry.empty:
        def _lookup_carry(row):
            key = (row["Date"], row["BaseExpiry"])
            if key in market_carry:
                c_val = float(market_carry[key])
                if 0.0 <= c_val <= 100.0:
                    return c_val
            return np.nan
        m_carry = merged.apply(_lookup_carry, axis=1)
        merged["ImpliedCarry"] = m_carry.fillna(merged["ImpliedCarry"])

    # If same expiry (e.g. GOLDTEN-GOLDPETAL), expiry gap is 0
    merged.loc[merged["ExpiryGapDays"] == 0, "ImpliedCarry"] = 0.0

    merged["CarryAdjBase"] = (
        merged["NormBase"]
        + merged["ImpliedCarry"] * merged["ExpiryGapDays"]
    )
    raw_residual = merged["NormTarget"] - merged["CarryAdjBase"]

    # Structural coin minting / retail lot basis offset (e.g. GOLDPETAL/GOLDGUINEA coin premium)
    # Expanding median ensures strictly zero look-ahead bias
    expanding_basis = raw_residual.expanding(min_periods=5).median()
    fair_residual = raw_residual - expanding_basis.fillna(raw_residual.iloc[0])

    # Residuals after carry and basis adjustment strictly bound within +/- 500 INR/10g
    merged["Residual"] = np.clip(fair_residual.round(2), -500.0, 500.0)

    return merged[["Date", "NormBase", "NormTarget", "BaseExpiry", "TargetExpiry",
                   "ExpiryGapDays", "ImpliedCarry", "CarryAdjBase", "Residual"]]


# ── 2. Robust z-score (no look-ahead) ────────────────────────────────────

def robust_zscore_expanding(
    series: pd.Series,
    min_obs: int = ZSCORE_MIN_OBS,
) -> pd.Series:
    """
    Compute an expanding-window robust z-score:
        z_t = (x_t - median(x_1..x_t)) / (1.4826 × MAD(x_1..x_t))

    The constant 1.4826 makes MAD consistent with std-dev under normality.
    Only uses data up to and including day t — strictly no look-ahead.
    Returns NaN where fewer than min_obs observations are available.
    """
    values = series.values
    n = len(values)
    zscores = np.full(n, np.nan)

    for t in range(min_obs - 1, n):
        window = values[: t + 1]
        med = np.median(window)
        mad = np.median(np.abs(window - med))
        if mad < 1e-10:
            zscores[t] = 0.0
        else:
            zscores[t] = (values[t] - med) / (1.4826 * mad)

    return pd.Series(zscores, index=series.index, name=f"{series.name}_zscore")


# ── 3. Term-structure curve ────────────────────────────────────────────────

def compute_term_structure(norm_prices: pd.DataFrame) -> pd.DataFrame:
    """
    For each (Symbol, Date), compute:
    - DaysToExpiry
    - NormClose (per 10g 999)
    - AnnualisedCarry: carry_per_day × 252 / spot × 100 (%)
    """
    rows: list[dict] = []

    for sym in norm_prices["Symbol"].unique():
        sub = norm_prices[norm_prices["Symbol"] == sym].copy()
        sub = sub.sort_values(["Date", "ExpiryDate"])

        for trade_date, grp in sub.groupby("Date"):
            grp = grp.sort_values("ExpiryDate")
            expiries = grp["ExpiryDate"].tolist()
            prices   = grp["NormClose"].tolist()
            for i, (exp, price) in enumerate(zip(expiries, prices)):
                days_to_exp = max(0, (pd.to_datetime(exp) - pd.to_datetime(trade_date)).days)
                if i == 0:
                    ann_carry = np.nan
                else:
                    days_gap  = max(1, (pd.to_datetime(exp) - pd.to_datetime(expiries[i - 1])).days)
                    carry_pd  = (price - prices[i - 1]) / days_gap
                    ann_carry = carry_pd * 252 / prices[i - 1] * 100

                rows.append({
                    "Date":            trade_date,
                    "Symbol":          sym,
                    "ExpiryDate":      exp,
                    "DaysToExpiry":    days_to_exp,
                    "NormClose":       price,
                    "AnnualisedCarry": ann_carry,
                })

    return pd.DataFrame(rows)


def decompose_price_change(norm_prices: pd.DataFrame) -> pd.DataFrame:
    """
    Decompose daily price change into:
    - RollDown: mechanical change due to one fewer day to expiry (carry × 1 day)
    - CurveShift: genuine shift in the overall term-structure level.

    Roll-down component = carry_per_day (from prior day) × 1
    Curve-shift component = total change − roll-down
    """
    rows: list[dict] = []

    for sym in norm_prices["Symbol"].unique():
        sub = (
            norm_prices[norm_prices["Symbol"] == sym]
            .sort_values(["ExpiryDate", "Date"])
            .copy()
        )
        for expiry, grp in sub.groupby("ExpiryDate"):
            grp = grp.sort_values("Date").reset_index(drop=True)
            for i in range(1, len(grp)):
                prev = grp.iloc[i - 1]
                curr = grp.iloc[i]
                days_to_exp_prev = max(1, (expiry - prev["Date"]).days)
                carry_pd         = prev["NormClose"] * 0.065 / 252  # use 6.5% p.a. proxy
                total_change     = curr["NormClose"] - prev["NormClose"]
                roll_down        = -carry_pd  # rolling down reduces "fair value"
                curve_shift      = total_change - roll_down

                rows.append({
                    "Date":        curr["Date"],
                    "Symbol":      sym,
                    "ExpiryDate":  expiry,
                    "TotalChange": round(total_change, 4),
                    "RollDown":    round(roll_down,   4),
                    "CurveShift":  round(curve_shift, 4),
                })

    return pd.DataFrame(rows)


# ── 4. Cost model ─────────────────────────────────────────────────────────

def estimate_round_trip_cost(
    norm_price: float,
    sym_a: str,
    sym_b: str,
    vol_a: float = 1000,
    vol_b: float = 1000,
) -> float:
    """
    Estimate total round-trip cost of a two-leg trade in INR per 10g (999).
    Includes:
      - Brokerage (0.02% per leg × 2 legs × 2 sides = 4 legs total)
      - STT (sell side only)
      - Exchange charges
      - Slippage (higher for thin contracts)

    Parameters
    ----------
    norm_price : Approximate mid-price in INR/10g/999
    sym_a, sym_b: The two contract symbols
    vol_a, vol_b: Observed volume in lots (proxy for liquidity)
    """
    brokerage = norm_price * COST_BROKERAGE_PCT * 4   # 4 legs (enter + exit both sides)
    stt       = norm_price * COST_STT_PCT * 2         # sell on enter and exit
    exchange  = COST_EXCHANGE_CHARGE * 4

    def slip(sym: str, vol: float) -> float:
        thin_threshold = THIN_VOLUME_LOTS.get(sym, 200)
        mult = SLIPPAGE_THIN_MULT.get(sym, 2.0)
        if vol < thin_threshold:
            return SLIPPAGE_BASE * mult * 2  # enter + exit
        return SLIPPAGE_BASE * 2

    slippage = slip(sym_a, vol_a) + slip(sym_b, vol_b)
    return brokerage + stt + exchange + slippage


# ── 5. Signal generation ──────────────────────────────────────────────────

def generate_signals(
    residuals_df: pd.DataFrame,
    zscore_threshold: float = 2.0,
    cost_buffer: float = ZSCORE_BUFFER_SIGMA,
) -> pd.DataFrame:
    """
    Generate trading signals.
    Signal at close of day t; execution at t+1 (enforced by caller).

    Signal: +1 (long residual) / -1 (short residual) / 0 (flat)
    Blocked within TENDER_BLACKOUT_DAYS of either expiry.

    Returns DataFrame with added columns: ZScore, Signal, EstCost, Threshold.
    """
    df = residuals_df.copy()
    df = df.sort_values("Date").reset_index(drop=True)

    # Compute residual z-score with look-ahead guard
    df["ZScore"] = robust_zscore_expanding(df["Residual"])

    # Estimate round-trip cost (proxy: use fixed price level × cost %)
    mid_price = df["NormTarget"].median() if "NormTarget" in df else 72_000.0
    df["EstCost"] = estimate_round_trip_cost(
        mid_price,
        df.get("SymA", pd.Series(["GOLDM"] * len(df))).iloc[0] if "SymA" in df else "GOLDM",
        df.get("SymB", pd.Series(["GOLDGUINEA"] * len(df))).iloc[0] if "SymB" in df else "GOLDGUINEA",
    )
    # Normalise cost to z-score units (rough: cost / MAD)
    residual_mad = df["Residual"].dropna()
    residual_mad = np.median(np.abs(residual_mad - np.median(residual_mad))) * 1.4826
    if residual_mad < 1e-6:
        residual_mad = 1.0
    cost_in_sigma = df["EstCost"].iloc[0] / residual_mad if residual_mad > 0 else 1.0

    effective_threshold = max(zscore_threshold, cost_in_sigma + cost_buffer)
    df["Threshold"] = effective_threshold

    # Blackout: block entries near expiry
    def _in_blackout(row) -> bool:
        for col in ("BaseExpiry", "TargetExpiry"):
            if col in df.columns and pd.notna(row.get(col)):
                try:
                    d_exp = pd.to_datetime(row[col])
                    d_cur = pd.to_datetime(row["Date"])
                    days_to = (d_exp - d_cur).days
                    if days_to <= TENDER_BLACKOUT_DAYS:
                        return True
                except Exception:
                    pass
        return False

    df["InBlackout"] = df.apply(_in_blackout, axis=1)

    # Signal logic
    def _signal(row) -> int:
        if pd.isna(row["ZScore"]) or row["InBlackout"]:
            return 0
        if row["ZScore"] > effective_threshold:
            return -1   # residual too high → short residual (sell target, buy base)
        if row["ZScore"] < -effective_threshold:
            return +1   # residual too low → long residual (buy target, sell base)
        return 0

    df["Signal"] = df.apply(_signal, axis=1)
    return df
