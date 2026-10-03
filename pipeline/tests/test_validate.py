"""
Unit tests for data validation, holiday/redirect handling, and OHLCV sanity.
"""

from datetime import date
import pandas as pd
import pytest
from pipeline.validate import (
    validate_response_date,
    clean_symbol,
    validate_ohlcv,
)


def test_validate_response_date_matching():
    req_date = date(2026, 3, 10)
    # Response date in MM/DD/YYYY format
    df = pd.DataFrame({
        "Date": ["03/10/2026", "03/10/2026"],
        "Close": [72000, 72100],
    })
    filtered, warns = validate_response_date(req_date, df)
    assert len(filtered) == 2
    assert len(warns) == 0


def test_validate_response_date_mismatched_holiday():
    req_date = date(2026, 3, 15)  # Suppose holiday, MCX returned latest trading day 03/13/2026
    df = pd.DataFrame({
        "Date": ["03/13/2026", "03/13/2026"],
        "Close": [72000, 72100],
    })
    filtered, warns = validate_response_date(req_date, df)
    # Must discard all rows because the returned date does not equal requested date
    assert len(filtered) == 0
    assert len(warns) == 1
    assert "discarded" in warns[0]


def test_clean_symbol():
    assert clean_symbol("  GOLDM  ") == "GOLDM"
    assert clean_symbol("goldten") == "GOLDTEN"
    assert clean_symbol("\tGOLDGUINEA\n") == "GOLDGUINEA"


def test_validate_ohlcv():
    df = pd.DataFrame({
        "Open": [72000, 72000, -10],
        "High": [72500, 71500, 73000],  # row 1: High < Low invalid
        "Low": [71800, 71800, 71000],
        "Close": [72200, 71700, 72000], # row 1: High < Low
        "Volume": [100, 50, 10],
        "OpenInterest": [500, 400, 100],
    })
    clean, warns = validate_ohlcv(df)
    # Only row 0 passes (Open > 0, High >= Low, Close between Low and High)
    assert len(clean) == 1
    assert clean.iloc[0]["Close"] == 72200


def test_load_local_raw_csvs_valid_and_keyed(tmp_path):
    from pipeline.fetch import load_local_raw_csvs

    # Create a mock valid raw MCX Bhavcopy CSV with date in filename
    csv_file = tmp_path / "bhavcopy_2026-03-10.csv"
    csv_file.write_text(
        "Symbol,Date,ExpiryDate,Open,High,Low,Close,Volume,OpenInterest\n"
        "GOLDM,03/10/2026,04SEP2026,72000,72500,71900,72200,1500,5000\n"
        "GOLDTEN,03/10/2026,28NOV2026,72100,72600,72000,72300,300,1200\n"
    )

    combined, n_accepted, n_rejected = load_local_raw_csvs(tmp_path)
    assert n_accepted == 1
    assert n_rejected == 0
    assert len(combined) == 2
    # Verify contract_key is keyed by (symbol, expiry_date)
    assert "contract_key" in combined.columns
    assert "GOLDM_2026-09-04" in combined["contract_key"].values
    assert "GOLDTEN_2026-11-28" in combined["contract_key"].values


def test_load_local_raw_csvs_date_mismatch_rejected(tmp_path):
    from pipeline.fetch import load_local_raw_csvs

    # Filename says 2026-03-15 (holiday), but MCX returned 03/13/2026
    csv_file = tmp_path / "bhavcopy_2026-03-15.csv"
    csv_file.write_text(
        "Symbol,Date,ExpiryDate,Open,High,Low,Close,Volume,OpenInterest\n"
        "GOLDM,03/13/2026,04SEP2026,72000,72500,71900,72200,1500,5000\n"
    )

    combined, n_accepted, n_rejected = load_local_raw_csvs(tmp_path)
    assert n_accepted == 0
    assert n_rejected == 1
    assert combined.empty
