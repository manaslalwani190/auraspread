"""
AuraSpread – normalize.py
Normalization of MCX gold contract prices to INR per 10 g of 999 gold.
This is the core unit-tested transformation.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

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
    sym = symbol.strip().upper() if isinstance(symbol, str) else symbol
    if sym not in contracts:
        raise ValueError(f"Unknown symbol: {symbol!r}. Expected one of {list(contracts)}")

    spec        = contracts[sym]
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


def deduplicate_nearest_contract(
    df: pd.DataFrame,
    date_col: str = "Date",
    symbol_col: str = "Symbol",
    expiry_col: str = "ExpiryDate",
    volume_col: str = "Volume",
) -> pd.DataFrame:
    """
    When multiple contract expiries exist for the same symbol on the same date,
    keep only the NEAREST expiry contract (highest volume or earliest expiry date).
    Picks ONE active contract per symbol per date.
    Never creates two rows for the same symbol+date.
    """
    if df.empty or expiry_col not in df.columns or date_col not in df.columns:
        return df

    clean = df.copy()
    exp_dt = pd.to_datetime(clean[expiry_col])
    date_dt = pd.to_datetime(clean[date_col])

    # Keep only active contracts (expiry on or after trade date)
    active = clean[exp_dt >= date_dt]
    if active.empty:
        active = clean

    # Consistent rolling logic:
    # Sort by trade date, symbol, expiry date (earliest active first), and volume (highest first)
    sort_cols = [date_col, symbol_col, expiry_col]
    ascending = [True, True, True]
    if volume_col in active.columns:
        sort_cols.append(volume_col)
        ascending.append(False)

    deduped = (
        active.sort_values(sort_cols, ascending=ascending)
        .groupby([date_col, symbol_col], as_index=False)
        .first()
    )
    return deduped


def build_normalized_panel(
    raw_df: pd.DataFrame,
    price_col: str = "Close",
    deduplicate: bool = True,
) -> pd.DataFrame:
    """
    Given a long-format DataFrame with columns
    [Date, Symbol, ExpiryDate, Open, High, Low, Close, Volume, OpenInterest],
    add a 'NormClose' column and return the enriched frame.

    When deduplicate=True, keeps only the NEAREST expiry contract per symbol per date.
    """
    df = raw_df.copy()
    if deduplicate:
        df = deduplicate_nearest_contract(df)
    df["NormClose"] = normalize_series(df, price_col=price_col)
    return df


# ── Purity adjustment factor (for display / documentation) ────────────────

def purity_factor(symbol: str, contracts: dict = CONTRACTS) -> float:
    """Return the purity-scaling factor (norm_purity / symbol_purity)."""
    sym = symbol.strip().upper() if isinstance(symbol, str) else symbol
    return NORM_PURITY / contracts[sym]["purity"]


def quote_unit_factor(symbol: str, contracts: dict = CONTRACTS) -> float:
    """Return the gram-scaling factor (norm_unit_g / quote_unit_g)."""
    sym = symbol.strip().upper() if isinstance(symbol, str) else symbol
    return NORM_UNIT_G / contracts[sym]["quote_unit_g"]


def total_norm_factor(symbol: str, contracts: dict = CONTRACTS) -> float:
    """Combined multiplier applied to raw price to get normalized price."""
    return purity_factor(symbol, contracts) * quote_unit_factor(symbol, contracts)


if __name__ == "__main__":
    print("=" * 68)
    print("AuraSpread - MCX Gold Contract Normalization Verification")
    print("Target: INR per 10g of 999 purity gold")
    print("=" * 68)

    # Baseline verification: near INR 75,000/10g
    print("\n[Baseline Contract Price Normalization ~ INR 75,000/10g]:")
    sample_raw = {
        "GOLDM": 74700.0,       # 10g quote, 995 purity -> × 999/995 = 75,000.30
        "GOLDTEN": 75000.0,     # 10g quote, 999 purity -> × 1.0     = 75,000.00
        "GOLDGUINEA": 60000.0,  # 8g quote,  999 purity -> × 10/8    = 75,000.00
        "GOLDPETAL": 7500.0,    # 1g quote,  999 purity -> × 10.0    = 75,000.00
    }
    norm_vals = {}
    for sym, raw_p in sample_raw.items():
        norm_p = normalize_price(raw_p, sym)
        norm_vals[sym] = norm_p
        tf = total_norm_factor(sym)
        print(f"  {sym:12s}: Raw = {raw_p:10.2f} | Factor = {tf:8.5f} | Norm = {norm_p:10.2f} INR/10g (999)")

    mean_norm = float(np.mean(list(norm_vals.values())))
    max_dev_pct = max(abs(v - mean_norm) / mean_norm for v in norm_vals.values()) * 100
    print(f"  --> Mean Normalized Price : INR {mean_norm:,.2f}/10g")
    print(f"  --> Max Deviation from Mean: {max_dev_pct:.4f}% (Well within +/-2% limit: {max_dev_pct <= 2.0})")

    # Historical data verification if processed cache exists
    from pipeline.config import DATA_PROC
    pq_path = DATA_PROC / "gold_contracts_clean.parquet"
    if pq_path.exists():
        try:
            hist_df = pd.read_parquet(pq_path)
            for d, grp in hist_df.groupby("Date"):
                syms = set(grp["Symbol"].str.strip())
                if {"GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL"}.issubset(syms):
                    print(f"\n[Historical MCX Bhavcopy Data Verification for Date: {d}]:")
                    hist_norms = {}
                    for sym in ["GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL"]:
                        row = grp[grp["Symbol"].str.strip() == sym].iloc[0]
                        rp = float(row["Close"])
                        np_val = normalize_price(rp, sym)
                        hist_norms[sym] = np_val
                        print(f"  {sym:12s}: Raw Close = {rp:10.2f} (Exp: {row['ExpiryDate']}) -> Norm = {np_val:10.2f} INR/10g")
                    h_mean = float(np.mean(list(hist_norms.values())))
                    h_dev = max(abs(v - h_mean) / h_mean for v in hist_norms.values()) * 100
                    print(f"  --> Mean: INR {h_mean:,.2f}/10g | Max Deviation: {h_dev:.2f}% (Within +/-2%: {h_dev <= 2.0})")
                    break
        except Exception as err:
            print(f"  (Parquet verification skipped: {err})")

