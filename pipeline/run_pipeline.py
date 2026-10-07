"""
AuraSpread – run_pipeline.py
Master orchestrator:
1. Attempts to fetch real MCX Bhavcopy data across the date range.
2. If MCX fails or returns insufficient data, falls back gracefully to synthetic data.
3. Computes normalization, carry adjustments, term structure, decomposition.
4. Generates signals with look-ahead guards.
5. Runs walk-forward backtests and attribution regression on gold returns.
6. Computes breakeven costs per pair.
7. Exports everything to web/data/auraspread_data.json.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config import (
    FETCH_START,
    FETCH_END,
    CONTRACTS,
    DATA_RAW,
    DATA_PROC,
    WEB_DATA,
)
from pipeline.normalize import build_normalized_panel
from pipeline.fetch import fetch_date_range, load_local_raw_csvs
from pipeline.synthetic import generate_synthetic
from pipeline.analysis import (
    PAIRS,
    estimate_carry_per_day,
    carry_adjusted_price,
    compute_term_structure,
    decompose_price_change,
    generate_signals,
    estimate_round_trip_cost,
)
from pipeline.backtest import run_backtest
from pipeline.attribution import (
    attribute_returns,
    compute_breakeven,
    build_gold_neutral_equity,
)
from pipeline.export import export_json, build_calendar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("auraspread.pipeline")


def run() -> None:
    log.info("=" * 60)
    log.info("Starting AuraSpread Quantitative Pipeline")
    log.info(f"Target Date Range: {FETCH_START} to {FETCH_END}")
    log.info("=" * 60)

    # ── Step 1: Data Ingestion (Local Raw CSV first, MCX fetch second, Synthetic fallback) ──
    is_synthetic = False
    data_source_msg = "MCX India Bhavcopy (Official Public Archive)"
    raw_df = pd.DataFrame()

    local_df, n_accepted, n_rejected = load_local_raw_csvs(DATA_RAW)
    if not local_df.empty and len(local_df["Date"].unique()) >= 15:
        log.info(f"Loaded {len(local_df)} rows from {n_accepted} raw CSV file(s) in {DATA_RAW} ({n_rejected} rejected).")
        raw_df = local_df
        is_synthetic = False
        data_source_msg = "MCX India Bhavcopy (Local Raw CSV Archive)"
    else:
        try:
            log.info("Attempting connection to MCX India Bhavcopy archive...")
            raw_df, failures, success = fetch_date_range(FETCH_START, FETCH_END)
            if not success or raw_df.empty or len(raw_df["Date"].unique()) < 15:
                log.warning("MCX unreachable, blocked by rate-limit/CORS/firewall, or returned insufficient records.")
                log.warning("Activating high-fidelity SYNTHETIC generator (Geometric Brownian Motion + Contango carry + Noise)...")
                is_synthetic = True
                raw_df = generate_synthetic(FETCH_START, FETCH_END)
                data_source_msg = "Synthetic Simulation Engine (GBM + MCX Contango & Liquidity Model)"
        except Exception as e:
            log.error(f"Error during MCX fetch: {e}. Switching to synthetic data.")
            is_synthetic = True
            raw_df = generate_synthetic(FETCH_START, FETCH_END)
            data_source_msg = "Synthetic Simulation Engine (GBM + MCX Contango & Liquidity Model)"

    # Save processed raw parquet / cache
    raw_parquet_path = DATA_PROC / "gold_contracts_clean.parquet"
    try:
        raw_df.to_parquet(raw_parquet_path, index=False)
        log.info(f"Saved processed parquet to {raw_parquet_path}")
    except Exception as e:
        log.warning(f"Could not write parquet (pyarrow missing?): {e}")

    # ── Step 2: Normalization to INR per 10g (999 Purity) ───────────────────
    log.info("Normalizing contract prices to INR per 10g of 999 gold...")
    norm_panel_full = build_normalized_panel(raw_df, deduplicate=False)
    norm_panel = build_normalized_panel(raw_df, deduplicate=True)

    # Prepare normalized_prices for export
    # Sample daily representative near-month prices
    norm_prices_export: list[dict] = []
    for _, row in norm_panel.sort_values(["Date", "Symbol"]).iterrows():
        norm_prices_export.append({
            "date": str(row["Date"]),
            "symbol": row["Symbol"],
            "expiry": str(row["ExpiryDate"]),
            "raw_close": float(row["Close"]),
            "norm_close": round(float(row["NormClose"]), 2),
            "volume": int(row["Volume"]),
            "oi": int(row["OpenInterest"]),
        })

    # Reference benchmark gold series (using GOLDM near month or GOLDTEN)
    goldm_near = (
        norm_panel[norm_panel["Symbol"] == "GOLDM"]
        .sort_values("ExpiryDate")
        .groupby("Date", as_index=False)
        .first()
        .sort_values("Date")
    )
    gold_benchmark_series = goldm_near.set_index("Date")["NormClose"]

    # ── Step 3: Carry & Residuals across Pairs ─────────────────────────────
    log.info("Computing carry adjustments and residual spreads across all pairs...")
    residuals_dict: dict[str, list[dict]] = {}
    zscores_dict: dict[str, list[dict]] = {}
    signals_dict: dict[str, list[dict]] = {}
    trades_dict: dict[str, list[dict]] = {}
    equity_dict: dict[str, dict] = {}
    attribution_dict: dict[str, dict] = {}
    breakeven_dict: dict[str, dict] = {}

    for sym_a, sym_b in PAIRS:
        pair_key = f"{sym_a}-{sym_b}"
        log.info(f"Processing pair: {pair_key}")

        carry_series = estimate_carry_per_day(norm_panel_full, sym_a)
        res_df = carry_adjusted_price(norm_panel, sym_a, sym_b, market_carry=carry_series)

        if res_df.empty:
            log.warning(f"No overlapping data for pair {pair_key}")
            continue

        res_df["SymA"] = sym_a
        res_df["SymB"] = sym_b

        # Signals with robust expanding z-score
        sig_df = generate_signals(res_df, zscore_threshold=2.0)

        # Export residuals & zscores
        res_list = []
        zscore_list = []
        sig_list = []

        for _, r in sig_df.iterrows():
            d_str = str(r["Date"])
            res_val = round(float(r["Residual"]), 2) if pd.notna(r["Residual"]) else None
            z_val = round(float(r["ZScore"]), 3) if pd.notna(r["ZScore"]) else None
            
            res_list.append({
                "date": d_str,
                "norm_base": round(float(r["NormBase"]), 2),
                "norm_target": round(float(r["NormTarget"]), 2),
                "carry_adj_base": round(float(r["CarryAdjBase"]), 2),
                "implied_carry": round(float(r["ImpliedCarry"]), 4) if pd.notna(r["ImpliedCarry"]) else None,
                "residual": res_val,
            })

            zscore_list.append({
                "date": d_str,
                "zscore": z_val,
                "threshold": round(float(r["Threshold"]), 3),
                "in_blackout": bool(r["InBlackout"]),
            })

            if r["Signal"] != 0:
                sig_list.append({
                    "date": d_str,
                    "signal": int(r["Signal"]),
                    "residual": res_val,
                    "zscore": z_val,
                    "action": "BUY SPREAD (Long Target / Short Base)" if r["Signal"] > 0 else "SELL SPREAD (Short Target / Long Base)",
                })

        residuals_dict[pair_key] = res_list
        zscores_dict[pair_key] = zscore_list
        signals_dict[pair_key] = sig_list

        # ── Step 4: Walk-forward Backtest ─────────────────────────────────
        bt_results = run_backtest(sig_df, sym_a, sym_b)
        trades_dict[pair_key] = bt_results["trades"]

        # Gold benchmark sliced for test period
        test_dates = bt_results["dates"]
        sliced_gold = None
        if test_dates:
            sliced_gold = gold_benchmark_series[gold_benchmark_series.index.astype(str).isin(test_dates)]

        # Attribution regression
        attr = attribute_returns(bt_results["equity_net"], sliced_gold)
        bt_results["metrics"]["beta_to_gold"] = attr["beta"]
        attribution_dict[pair_key] = attr

        # Gold neutral equity curve
        gold_neutral_curve = build_gold_neutral_equity(
            bt_results["equity_net"],
            sliced_gold,
            attr["beta"],
        )

        equity_dict[pair_key] = {
            "dates": bt_results["dates"],
            "equity_gross": bt_results["equity_gross"],
            "equity_net": bt_results["equity_net"],
            "equity_gold_neutral": gold_neutral_curve,
            "drawdown": bt_results.get("drawdown", []),
            "split_date": bt_results["split_date"],
            "metrics": bt_results["metrics"],
        }

        # Breakeven analysis
        est_cost = estimate_round_trip_cost(72000.0, sym_a, sym_b)
        be = compute_breakeven(bt_results["trades"], est_cost)
        breakeven_dict[pair_key] = be

    # ── Step 5: Term Structure Curve & Price Decomposition ─────────────────
    log.info("Calculating term structure and mechanical roll-down decomposition...")
    curve_df = compute_term_structure(norm_panel_full)
    curve_export = [
        {
            "date": str(r["Date"]),
            "symbol": r["Symbol"],
            "expiry": str(r["ExpiryDate"]),
            "days_to_expiry": int(r["DaysToExpiry"]),
            "norm_close": round(float(r["NormClose"]), 2),
            "annualised_carry": round(float(r["AnnualisedCarry"]), 2) if pd.notna(r["AnnualisedCarry"]) else None,
        }
        for _, r in curve_df.iterrows()
    ]

    decomp_df = decompose_price_change(norm_panel_full)
    decomp_export = [
        {
            "date": str(r["Date"]),
            "symbol": r["Symbol"],
            "expiry": str(r["ExpiryDate"]),
            "total_change": float(r["TotalChange"]),
            "roll_down": float(r["RollDown"]),
            "curve_shift": float(r["CurveShift"]),
        }
        for _, r in decomp_df.iterrows()
    ]

    calendar = build_calendar()

    actual_start = str(raw_df["Date"].min()) if not raw_df.empty and "Date" in raw_df.columns else str(FETCH_START)
    actual_end   = str(raw_df["Date"].max()) if not raw_df.empty and "Date" in raw_df.columns else str(FETCH_END)
    actual_sessions = int(raw_df["Date"].nunique()) if not raw_df.empty and "Date" in raw_df.columns else 0

    meta = {
        "is_synthetic": is_synthetic,
        "data_source": data_source_msg,
        "date_start": actual_start,
        "date_end": actual_end,
        "trading_sessions": actual_sessions,
        "total_records": len(raw_df),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "norm_target": "INR per 10g (999 Purity Gold)",
        "contracts_tracked": list(CONTRACTS.keys()),
        "pairs_tracked": [f"{a}-{b}" for a, b in PAIRS],
    }

    # ── Step 6: Export Master JSON ─────────────────────────────────────────
    log.info("Exporting consolidated JSON dataset...")
    out_path = export_json(
        meta=meta,
        normalized_prices=norm_prices_export,
        residuals=residuals_dict,
        zscores=zscores_dict,
        curve=curve_export,
        decomposition=decomp_export,
        signals=signals_dict,
        trades=trades_dict,
        equity_curves=equity_dict,
        attribution=attribution_dict,
        breakeven=breakeven_dict,
        calendar=calendar,
    )

    log.info("=" * 60)
    log.info(f"Pipeline finished successfully! Output generated at: {out_path}")
    log.info("=" * 60)


if __name__ == "__main__":
    run()
