"""
AuraSpread – synthetic.py
Generates a realistic synthetic dataset when MCX is unreachable.
NEVER presented as real data — always flagged with IS_SYNTHETIC=True.

Realistic features:
- Gold price follows a geometric Brownian motion anchored near spot
- Each contract has purity/lot-size-appropriate raw prices
- Carry structure: GOLDM expires ~25 days before end-of-month contracts
- GOLDTEN listed only from 2025-01-01
- Thin days: weekend-like gaps, occasional zero-volume days
- Noise scaled to contract liquidity
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from pipeline.config import (
    CONTRACTS,
    SYNTHETIC_SEED,
    NORM_UNIT_G,
    NORM_PURITY,
    FETCH_START,
    FETCH_END,
)

log = logging.getLogger(__name__)

IS_SYNTHETIC = True   # module-level flag checked by run_pipeline


# ── Trading calendar (simplified: skip weekends + ~10 Indian holidays/yr) ──

def _trading_days(start: date, end: date, rng: np.random.Generator) -> list[date]:
    days = []
    current = start
    # Pick ~10 random "holiday" dates per year to skip
    total_days = (end - start).days
    n_holidays = max(1, int(total_days / 365 * 10))
    holiday_offsets = set(rng.integers(0, max(1, total_days), size=n_holidays).tolist())
    idx = 0
    while current <= end:
        if current.weekday() < 5 and idx not in holiday_offsets:
            days.append(current)
        current += timedelta(days=1)
        idx += 1
    return days


# ── Contract expiry calendar ───────────────────────────────────────────────

def _monthly_expiries(
    symbol: str,
    start: date,
    end: date,
) -> list[date]:
    """Generate one expiry per month for the symbol in [start, end]."""
    spec = CONTRACTS[symbol]
    low, high = spec["expiry_day_range"]
    expiry_day = (low + high) // 2   # pick midpoint: e.g. 4 for GOLDM, 29 for others

    expiries = []
    y, m = start.year, start.month
    while True:
        try:
            exp = date(y, m, expiry_day)
        except ValueError:
            # day out of range for month (e.g. Feb 29)
            exp = date(y, m, 28)
        if exp > end:
            break
        if exp >= spec["listed_from"]:
            expiries.append(exp)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return expiries


# ── Synthetic price generation ────────────────────────────────────────────

def generate_synthetic(
    start: date = FETCH_START,
    end: date = FETCH_END,
    seed: int = SYNTHETIC_SEED,
) -> pd.DataFrame:
    """
    Return a long-format DataFrame mimicking real Bhavcopy data.
    Columns: Date, Symbol, ExpiryDate, Open, High, Low, Close, Volume, OpenInterest
    """
    rng = np.random.default_rng(seed)
    trading_days = _trading_days(start, end, rng)
    n_days = len(trading_days)

    # ── Gold spot GBM ─────────────────────────────────────────────────────
    SPOT_INIT   = 72_000.0   # INR per 10 g of 999 gold (≈ Oct 2026 level)
    DAILY_SIGMA = 0.0080     # ~1.3% daily vol
    DAILY_MU    = 0.0003     # slight upward drift

    log_returns = rng.normal(DAILY_MU - 0.5 * DAILY_SIGMA**2, DAILY_SIGMA, n_days)
    spot_999 = SPOT_INIT * np.exp(np.cumsum(log_returns))

    # ── Per-contract raw price (reverse the normalization) ────────────────
    # raw = normalized / total_factor
    # total_factor = (NORM_PURITY / purity) * (NORM_UNIT_G / quote_unit_g)
    def raw_from_norm(norm: float, symbol: str) -> float:
        spec = CONTRACTS[symbol]
        factor = (NORM_PURITY / spec["purity"]) * (NORM_UNIT_G / spec["quote_unit_g"])
        return norm / factor

    rows: list[dict] = []

    for sym, spec in CONTRACTS.items():
        if not trading_days:
            continue
        sym_start = max(start, spec["listed_from"])
        expiries = _monthly_expiries(sym, sym_start, end + timedelta(days=90))
        if not expiries:
            continue

        # Carry parameters per contract type
        ANNUAL_CARRY_RATE = 0.065   # 6.5% p.a.
        DAILY_CARRY = ANNUAL_CARRY_RATE / 252

        # Liquidity noise (GOLDPETAL noisiest, GOLDM most liquid)
        liq_noise = {
            "GOLDM": 0.0003, "GOLDTEN": 0.0008,
            "GOLDGUINEA": 0.0015, "GOLDPETAL": 0.0025,
        }[sym]

        # Volume baseline (lots/day)
        vol_base = {
            "GOLDM": 8000, "GOLDTEN": 300,
            "GOLDGUINEA": 1500, "GOLDPETAL": 25000,
        }[sym]

        for i, trade_date in enumerate(trading_days):
            if trade_date < sym_start:
                continue

            # Find near and next expiry
            future_expiries = [e for e in expiries if e >= trade_date]
            if not future_expiries:
                continue
            near_exp = future_expiries[0]
            next_exp = future_expiries[1] if len(future_expiries) > 1 else near_exp

            days_to_exp = (near_exp - trade_date).days
            if days_to_exp < 0:
                continue

            # Near contract price = spot + carry for days remaining
            # Slight contango structure
            norm_close = spot_999[i] * (1 + DAILY_CARRY * max(days_to_exp, 1))
            norm_close += rng.normal(0, spot_999[i] * liq_noise)  # idiosyncratic noise

            raw_close = raw_from_norm(norm_close, sym)

            # OHLC from close
            intraday_range = raw_close * rng.uniform(0.002, 0.008)
            raw_open   = raw_close + rng.normal(0, raw_close * 0.001)
            raw_high   = max(raw_open, raw_close) + rng.uniform(0, intraday_range)
            raw_low    = min(raw_open, raw_close) - rng.uniform(0, intraday_range)
            raw_open   = max(raw_open, raw_low)

            # Volume (occasionally thin or zero)
            thin_prob = {"GOLDM": 0.02, "GOLDTEN": 0.15, "GOLDGUINEA": 0.10, "GOLDPETAL": 0.05}[sym]
            if rng.random() < thin_prob:
                volume = rng.integers(0, 20)
                oi     = max(0, int(vol_base * 0.1 * rng.uniform(0.5, 1.5)))
            else:
                volume = max(1, int(rng.normal(vol_base, vol_base * 0.3)))
                oi     = max(0, int(vol_base * rng.uniform(2.0, 8.0)))

            rows.append({
                "Date":          trade_date,
                "Symbol":        sym,
                "ExpiryDate":    near_exp,
                "contract_key":  f"{sym}_{near_exp}",
                "Open":          round(raw_open,  2),
                "High":          round(raw_high,  2),
                "Low":           round(raw_low,   2),
                "Close":         round(raw_close, 2),
                "Volume":        volume,
                "OpenInterest":  oi,
            })

    df = pd.DataFrame(rows)
    df.sort_values(["Symbol", "ExpiryDate", "Date"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    log.info(
        f"[SYNTHETIC] Generated {len(df)} rows for "
        f"{df['Symbol'].nunique()} symbols × "
        f"{df['Date'].nunique()} days"
    )
    return df
