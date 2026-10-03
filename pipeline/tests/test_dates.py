"""
Unit tests for date parsing and formatting.
"""

from datetime import date
import pytest
from pipeline.validate import (
    parse_request_date,
    parse_response_date,
    parse_expiry_date,
)


def test_parse_request_date():
    d = date(2026, 9, 4)
    assert parse_request_date(d) == "04/09/2026"


def test_parse_response_date():
    # MCX response is MM/DD/YYYY
    d_str = "09/04/2026"
    expected = date(2026, 9, 4)
    assert parse_response_date(d_str) == expected


def test_parse_response_date_with_whitespace():
    d_str = "  12/25/2025  \n"
    expected = date(2025, 12, 25)
    assert parse_response_date(d_str) == expected


def test_parse_expiry_date():
    # MCX expiry format e.g. 04SEP2026 or 28NOV2025
    assert parse_expiry_date("04SEP2026") == date(2026, 9, 4)
    assert parse_expiry_date("  28nov2025  ") == date(2025, 11, 28)
    assert parse_expiry_date("05MAY2025") == date(2025, 5, 5)


def test_parse_invalid_dates():
    with pytest.raises(ValueError):
        parse_response_date("invalid-date")
    with pytest.raises(ValueError):
        parse_expiry_date("32DEC2026")


def test_parse_leap_year_and_casing():
    # Leap year 2024
    assert parse_expiry_date("29feb2024") == date(2024, 2, 29)
    # Different casings
    assert parse_expiry_date("04SeP2026") == date(2026, 9, 4)
    assert parse_expiry_date("31OcT2025") == date(2025, 10, 31)


def test_date_round_trip():
    original = date(2026, 8, 15)
    req_str = parse_request_date(original)  # DD/MM/YYYY: 15/08/2026
    assert req_str == "15/08/2026"
