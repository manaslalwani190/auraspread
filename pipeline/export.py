"""
AuraSpread – export.py
Assembles all computed artefacts into a single JSON file for the web frontend.
Schema matches the JavaScript loader expectations exactly.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pipeline.config import WEB_DATA, CONTRACTS

log = logging.getLogger(__name__)

OUTPUT_FILE = WEB_DATA / "auraspread_data.json"


class _Encoder(json.JSONEncoder):
    """Handle numpy, pandas, and date types."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj) if not np.isnan(obj) else None
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (pd.Timestamp, datetime)):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, pd.Series):
            return obj.tolist()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
        return super().default(obj)


def _safe(obj: Any) -> Any:
    """Recursively replace NaN/Inf with None for JSON safety."""
    if isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe(v) for v in obj]
    return obj


def export_json(
    meta: dict,
    normalized_prices: list[dict],
    residuals: dict[str, list[dict]],
    zscores: dict[str, list[dict]],
    curve: list[dict],
    decomposition: list[dict],
    signals: dict[str, list[dict]],
    trades: dict[str, list[dict]],
    equity_curves: dict[str, dict],
    attribution: dict[str, dict],
    breakeven: dict[str, dict],
    calendar: list[dict],
) -> Path:
    """
    Write the master JSON output file.
    All keys match the JS data loader in web/js/data.js.
    """
    # Enforce correct beta value range [-2.0, 2.0] for all pairs
    for pair, eq in equity_curves.items():
        if isinstance(eq, dict) and "metrics" in eq and "beta_to_gold" in eq["metrics"]:
            b = eq["metrics"]["beta_to_gold"]
            if b is not None and not np.isnan(b):
                eq["metrics"]["beta_to_gold"] = round(float(max(-2.0, min(2.0, b))), 4)

    for pair, attr in attribution.items():
        if isinstance(attr, dict) and "beta" in attr:
            b = attr["beta"]
            if b is not None and not np.isnan(b):
                attr["beta"] = round(float(max(-2.0, min(2.0, b))), 4)

    payload = {
        "meta":              meta,
        "normalized_prices": normalized_prices,
        "residuals":         residuals,
        "zscores":           zscores,
        "curve":             curve,
        "decomposition":     decomposition,
        "signals":           signals,
        "trades":            trades,
        "equity_curves":     equity_curves,
        "attribution":       attribution,
        "breakeven":         breakeven,
        "calendar":          calendar,
    }

    safe_payload = _safe(payload)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(safe_payload, f, cls=_Encoder, indent=2)

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    log.info(f"Exported {OUTPUT_FILE} ({size_kb:.1f} KB)")

    # Also sync to docs/data if docs directory exists
    docs_data_dir = OUTPUT_FILE.parent.parent.parent / "docs" / "data"
    if docs_data_dir.parent.exists():
        docs_data_dir.mkdir(parents=True, exist_ok=True)
        docs_file = docs_data_dir / "auraspread_data.json"
        with docs_file.open("w", encoding="utf-8") as f:
            json.dump(safe_payload, f, cls=_Encoder, indent=2)
        log.info(f"Synced exported data to {docs_file}")

    return OUTPUT_FILE


def build_calendar() -> list[dict]:
    """
    Build the contract lifecycle calendar entries.
    For each contract, list: listed_from, description, expiry_day_range,
    tender_period (5 days before expiry), purity, lot_size.
    """
    entries = []
    for sym, spec in CONTRACTS.items():
        entries.append({
            "symbol":          sym,
            "listed_from":     spec["listed_from"].isoformat(),
            "lot_size":        spec["lot_size"],
            "quote_unit_g":    spec["quote_unit_g"],
            "purity":          spec["purity"],
            "expiry_day_range": list(spec["expiry_day_range"]),
            "tender_days_before_expiry": 5,
            "notes": (
                "GOLDTEN listed from Jan 2025 — lower-confidence comparisons before Jul 2025."
                if sym == "GOLDTEN" else
                "GOLDM expiry 3rd–5th; ~25 days before end-of-month contracts."
                if sym == "GOLDM" else
                f"{sym}: end-of-month expiry, purity {spec['purity']}."
            ),
        })
    return entries
