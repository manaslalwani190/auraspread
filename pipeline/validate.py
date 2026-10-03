"""
AuraSpread – validate.py
Date parsing, date validation, and data-quality checks.
Unit-tested in tests/test_validate.py and tests/test_dates.py
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd

from pipeline.config import (
    MCX_DATE_REQUEST_FMT,
    MCX_DATE_RESPONSE_FMT,
    MCX_EXPIRY_FMT,
)

log = logging.getLogger(__name__)


# ── Date parsing ──────────────────────────────────────────────────────────

def parse_request_date(d: date) -> str:
    """Format a Python date as the MCX request string (DD/MM/YYYY)."""
    return d.strftime(MCX_DATE_REQUEST_FMT)


def parse_response_date(s: str) -> date:
    """
    Parse an MCX response Date field to a Python date.
    Handles multiple observed formats:
      - "01 Oct 2026"  (DD Mon YYYY) — real BhavCopyDateWise CSVs
      - "01 OCT 2026"  (case-insensitive)
      - "MM/DD/YYYY"   — older / API format
    Raises ValueError if none match.
    """
    s = s.strip()
    for fmt in ("%d %b %Y", "%d %B %Y", MCX_DATE_RESPONSE_FMT):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Cannot parse MCX date: {s!r}")


def parse_expiry_date(s: str) -> date:
    """
    Parse MCX ExpiryDate field, e.g. '04SEP2026' → date(2026, 9, 4).
    Strips whitespace and upper-cases the month abbreviation.
    """
    s = s.strip().upper()
    return datetime.strptime(s, MCX_EXPIRY_FMT).date()


# ── Response-date validation ───────────────────────────────────────────────

def validate_response_date(
    requested_date: date,
    raw_df: pd.DataFrame,
    date_col: str = "Date",
) -> tuple[pd.DataFrame, list[str]]:
    """
    MCX returns the latest trading day for holidays / future / malformed dates.
    This function keeps only rows where the response Date equals the requested date,
    discarding the rest as 'redirect' artefacts.

    Returns (filtered_df, list_of_warning_messages).
    """
    warnings: list[str] = []

    if raw_df.empty:
        return raw_df, warnings

    parsed_dates: list[date] = []
    for val in raw_df[date_col]:
        try:
            parsed_dates.append(parse_response_date(str(val)))
        except ValueError:
            parsed_dates.append(date(1900, 1, 1))  # sentinel for bad dates

    raw_df = raw_df.copy()
    raw_df["_parsed_date"] = parsed_dates
    mask = raw_df["_parsed_date"] == requested_date

    n_discarded = (~mask).sum()
    if n_discarded > 0:
        wrong_dates = raw_df.loc[~mask, "_parsed_date"].unique().tolist()
        msg = (
            f"[VALIDATE] Requested {requested_date}, but MCX returned "
            f"{n_discarded} row(s) dated {wrong_dates} — discarded."
        )
        log.warning(msg)
        warnings.append(msg)

    return raw_df[mask].drop(columns=["_parsed_date"]).reset_index(drop=True), warnings


# ── Symbol normalisation ───────────────────────────────────────────────────

def clean_symbol(s: str) -> str:
    """Strip padding and upper-case symbol strings from MCX."""
    return s.strip().upper()


# ── OHLCV sanity checks ────────────────────────────────────────────────────

def validate_ohlcv(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Basic sanity checks on OHLCV data:
    - High >= Low
    - Close between Low and High
    - Open > 0, Volume >= 0, OI >= 0
    Drops bad rows and logs them.
    """
    warnings: list[str] = []
    before = len(df)

    mask = (
        (df["High"] >= df["Low"])
        & (df["Close"] >= df["Low"])
        & (df["Close"] <= df["High"])
        & (df["Open"] > 0)
        & (df["Volume"] >= 0)
        & (df["OpenInterest"] >= 0)
    )
    bad = df[~mask]
    if not bad.empty:
        msg = f"[VALIDATE] Dropping {len(bad)} rows failing OHLCV sanity: {bad.index.tolist()}"
        log.warning(msg)
        warnings.append(msg)

    return df[mask].reset_index(drop=True), warnings


# ── Thin-day detection ────────────────────────────────────────────────────

def is_thin_day(volume_lots: float, symbol: str, thresholds: dict) -> bool:
    """Return True if volume is below the thin-day threshold for a symbol."""
    threshold = thresholds.get(symbol, 200)
    return volume_lots < threshold
