"""
Unit tests for price normalization across all four MCX gold contracts.
Standard target: INR per 10 g of 999 purity gold.
- GOLDM:      quoted per 10 g, purity 995 -> multiply by 999 / 995
- GOLDTEN:    quoted per 10 g, purity 999 -> multiply by 1.0 (as is)
- GOLDGUINEA: quoted per  8 g, purity 999 -> multiply by 10 / 8 = 1.25
- GOLDPETAL:  quoted per  1 g, purity 999 -> multiply by 10 / 1 = 10.0
"""

import pytest
import pandas as pd
from pipeline.normalize import (
    normalize_price,
    normalize_series,
    purity_factor,
    quote_unit_factor,
    total_norm_factor,
)


def test_goldm_normalization():
    # 72,000 raw price per 10g of 995 purity
    raw_price = 72000.0
    norm = normalize_price(raw_price, "GOLDM")
    expected = 72000.0 * (999.0 / 995.0)
    assert pytest.approx(norm, rel=1e-6) == expected
    assert pytest.approx(total_norm_factor("GOLDM"), rel=1e-6) == 999.0 / 995.0


def test_goldten_normalization():
    # 72,000 raw price per 10g of 999 purity -> unchanged
    raw_price = 72000.0
    norm = normalize_price(raw_price, "GOLDTEN")
    expected = 72000.0
    assert pytest.approx(norm, rel=1e-6) == expected
    assert pytest.approx(total_norm_factor("GOLDTEN"), rel=1e-6) == 1.0


def test_goldguinea_normalization():
    # 57,600 raw price per 8g of 999 purity -> (57,600 / 8) * 10 = 72,000
    raw_price = 57600.0
    norm = normalize_price(raw_price, "GOLDGUINEA")
    expected = 57600.0 * (10.0 / 8.0)
    assert pytest.approx(norm, rel=1e-6) == expected
    assert pytest.approx(total_norm_factor("GOLDGUINEA"), rel=1e-6) == 1.25


def test_goldpetal_normalization():
    # 7,200 raw price per 1g of 999 purity -> 7,200 * 10 = 72,000
    raw_price = 7200.0
    norm = normalize_price(raw_price, "GOLDPETAL")
    expected = 7200.0 * 10.0
    assert pytest.approx(norm, rel=1e-6) == expected
    assert pytest.approx(total_norm_factor("GOLDPETAL"), rel=1e-6) == 10.0


def test_unknown_symbol_error():
    with pytest.raises(ValueError):
        normalize_price(72000.0, "UNKNOWN_GOLD")


def test_normalize_series():
    df = pd.DataFrame({
        "Symbol": ["GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL"],
        "Close": [72000.0, 72000.0, 57600.0, 7200.0],
    })
    series = normalize_series(df, price_col="Close", symbol_col="Symbol")
    assert pytest.approx(series[0], rel=1e-6) == 72000.0 * (999.0 / 995.0)
    assert pytest.approx(series[1], rel=1e-6) == 72000.0
    assert pytest.approx(series[2], rel=1e-6) == 72000.0
    assert pytest.approx(series[3], rel=1e-6) == 72000.0


def test_build_normalized_panel():
    from pipeline.normalize import build_normalized_panel
    df = pd.DataFrame({
        "Date": ["2026-03-10"] * 4,
        "Symbol": ["GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL"],
        "ExpiryDate": ["2026-04-05", "2026-04-28", "2026-04-28", "2026-04-28"],
        "Close": [72000.0, 72289.0, 57831.2, 7228.9],
    })
    panel = build_normalized_panel(df)
    assert "NormClose" in panel.columns
    # Check that normalized prices are all in the sensible ~72,000 - 72,500 range
    for val in panel["NormClose"]:
        assert 72000.0 <= val <= 72500.0
