"""
AuraSpread – normalize.py
Normalization of MCX gold contract prices to INR per 10 g of 999 gold.
This is the core unit-tested transformation.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from pipeline.config import CONTRACTS, NORM_UNIT_G, NORM_PURITY


# ── Core normalization function ───────────────────────────────────────────

def normalize_price(
    price: float,
    symbol: str,
    contracts: dict = CONTRACTS,
    norm_unit_g: int = NORM_UNIT_G,
    norm_purity: int = NORM_PURITY,
) -> float:
    """
    Convert a raw MCX close price to INR per `norm_unit_g` grams of
    `norm_purity` gold.

    Formula per contract:
        price_per_norm_g = price / quote_unit_g * norm_unit_g
        price_999        = price_per_norm_g * norm_purity / purity

    GOLDM     (995, quoted per 10 g):  × (999/995) × (10/10)  = × 1.004020…
    GOLDTEN   (999, quoted per 10 g):  × (999/999) × (10/10)  = × 1.0
    GOLDGUINEA(999, quoted per  8 g):  × (999/999) × (10/ 8)  = × 1.25
    GOLDPETAL (999, quoted per  1 g):  × (999/999) × (10/ 1)  = × 10.0

    Parameters
    ----------
    price      : Raw MCX close price in INR (per quote_unit_g of own purity)
    symbol     : One of GOLDM / GOLDTEN / GOLDGUINEA / GOLDPETAL
    contracts  : Contract spec dict (injectable for testing)
    norm_unit_g: Target grams (default 10)
    norm_purity: Target purity (default 999)

    Returns
    -------
    float : Normalised price in INR per norm_unit_g of norm_purity gold
    """
    if symbol not in contracts:
        raise ValueError(f"Unknown symbol: {symbol!r}. Expected one of {list(contracts)}")

    spec        = contracts[symbol]
    quote_unit  = spec["quote_unit_g"]
    purity      = spec["purity"]

    # Step 1: convert to INR per 1 g of own purity
    per_gram_own = price / quote_unit
    # Step 2: scale to norm_unit_g
    per_norm_unit_own = per_gram_own * norm_unit_g
    # Step 3: adjust for purity
    per_norm_unit_999 = per_norm_unit_own * (norm_purity / purity)

    return per_norm_unit_999


def normalize_series(
    df: pd.DataFrame,
    price_col: str = "Close",
    symbol_col: str = "Symbol",
    **kwargs,
) -> pd.Series:
    """
    Apply normalize_price row-wise to a DataFrame.
    Returns a Series of normalized prices, same index as df.
    """
    return df.apply(
        lambda row: normalize_price(row[price_col], row[symbol_col], **kwargs),
        axis=1,
    )


def build_normalized_panel(
    raw_df: pd.DataFrame,
    price_col: str = "Close",
) -> pd.DataFrame:
    """
    Given a long-format DataFrame with columns
    [Date, Symbol, ExpiryDate, Open, High, Low, Close, Volume, OpenInterest],
    add a 'NormClose' column and return the enriched frame.
    """
    df = raw_df.copy()
    df["NormClose"] = normalize_series(df, price_col=price_col)
    return df


# ── Purity adjustment factor (for display / documentation) ────────────────

def purity_factor(symbol: str, contracts: dict = CONTRACTS) -> float:
    """Return the purity-scaling factor (norm_purity / symbol_purity)."""
    return NORM_PURITY / contracts[symbol]["purity"]


def quote_unit_factor(symbol: str, contracts: dict = CONTRACTS) -> float:
    """Return the gram-scaling factor (norm_unit_g / quote_unit_g)."""
    return NORM_UNIT_G / contracts[symbol]["quote_unit_g"]


def total_norm_factor(symbol: str, contracts: dict = CONTRACTS) -> float:
    """Combined multiplier applied to raw price to get normalized price."""
    return purity_factor(symbol, contracts) * quote_unit_factor(symbol, contracts)
