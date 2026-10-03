"""
AuraSpread – fetch.py
Downloads MCX Bhavcopy CSVs, caches them, validates dates, and returns
a clean DataFrame.  Never calls the site from the web frontend (CORS).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests
import pandas as pd

from pipeline.config import (
    DATA_RAW,
    MCX_URL,
    MCX_DATE_REQUEST_FMT,
    MCX_DATE_RESPONSE_FMT,
    REQUEST_TIMEOUT_S,
    RATE_LIMIT_DELAY_S,
    MAX_RETRIES,
    CONTRACTS,
)
from pipeline.validate import (
    parse_request_date,
    parse_response_date,
    parse_expiry_date,
    validate_response_date,
    clean_symbol,
    validate_ohlcv,
)

log = logging.getLogger(__name__)

GOLD_SYMBOLS = set(CONTRACTS.keys())

# -- Cache helpers ---------------------------------------------------------

def _cache_path(d: date) -> Path:
    return DATA_RAW / f"bhavcopy_{d.isoformat()}.json"


def _load_cache(d: date) -> Optional[pd.DataFrame]:
    p = _cache_path(d)
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            df = pd.DataFrame(data)
            log.debug(f"Cache hit: {p.name}")
            return df
        except Exception as e:
            log.warning(f"Cache corrupt for {d}: {e} -- re-fetching")
            p.unlink(missing_ok=True)
    return None


def _save_cache(d: date, df: pd.DataFrame) -> None:
    p = _cache_path(d)
    with p.open("w", encoding="utf-8") as f:
        json.dump(df.to_dict(orient="records"), f, default=str)
    log.debug(f"Cached {len(df)} rows -> {p.name}")


# -- MCX HTTP fetch --------------------------------------------------------

def _fetch_mcx_raw(d: date) -> Optional[pd.DataFrame]:
    """
    POST to MCX Bhavcopy endpoint and parse the CSV response.
    Returns None on failure.
    """
    date_str = parse_request_date(d)
    headers = {
        "User-Agent": "Mozilla/5.0 (AuraSpread-Research/1.0; academic use)",
        "Referer":    MCX_URL,
        "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # MCX uses a GET with date parameter
            params = {"frmDt": date_str, "toDt": date_str, "commodity": "Gold"}
            resp = requests.get(
                MCX_URL,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT_S,
            )
            if resp.status_code != 200:
                log.warning(f"MCX {d}: HTTP {resp.status_code} (attempt {attempt})")
                time.sleep(RATE_LIMIT_DELAY_S * attempt)
                continue

            content = resp.text.strip()
            if not content or "No Data" in content or len(content) < 50:
                log.info(f"MCX {d}: empty / no-data response")
                return None

            # Try CSV parse
            try:
                df = pd.read_csv(io.StringIO(content))
                return df
            except Exception:
                log.warning(f"MCX {d}: could not parse CSV (attempt {attempt})")
                time.sleep(RATE_LIMIT_DELAY_S)
                continue

        except requests.RequestException as exc:
            log.warning(f"MCX {d}: request error {exc} (attempt {attempt})")
            time.sleep(RATE_LIMIT_DELAY_S * attempt)

    return None


# -- Column normalisation ---------------------------------------------------
# Real MCX BhavCopyDateWise columns (after lower-strip):
#   'date', 'instrument name', 'symbol', 'expiry date', 'option type',
#   'strike price', 'open', 'high', 'low', 'close', 'previous close',
#   'volume(lots)', "volume(in 000's)", 'value(lacs)', 'open interest(lots)'

_COLUMN_MAP = {
    # Canonical commodity name
    "symbol":              "Symbol",
    # Instrument type (FUTCOM / OPTFUT)
    "instrument name":     "InstrumentName",
    "instrument_name":     "InstrumentName",
    # Option type (CE / PE / - )
    "option type":         "OptionType",
    "option_type":         "OptionType",
    # Dates
    "expiry date":         "ExpiryDate",
    "expiry_date":         "ExpiryDate",
    "expirydate":          "ExpiryDate",
    "expiry":              "ExpiryDate",
    "date":                "Date",
    # OHLCV
    "open":                "Open",
    "high":                "High",
    "low":                 "Low",
    "close":               "Close",
    "previous close":      "PrevClose",
    "prev. close":         "PrevClose",
    "prev_close":          "PrevClose",
    "prevclose":           "PrevClose",
    "volume(lots)":        "Volume",
    "volume":              "Volume",
    "open interest(lots)": "OpenInterest",
    "open interest":       "OpenInterest",
    "open_interest":       "OpenInterest",
    "openinterest":        "OpenInterest",
    "oi":                  "OpenInterest",
}

# Columns we strictly require after mapping
_REQUIRED_COLS = {"Symbol", "InstrumentName", "Date", "ExpiryDate",
                  "Open", "High", "Low", "Close", "Volume", "OpenInterest"}

# Futures instrument name as it appears in real MCX files
_FUTCOM_NAME = "FUTCOM"


def _normalise_columns(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.rename(columns=_COLUMN_MAP)
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        log.error(f"MCX response missing columns: {missing}  (got {list(df.columns)})")
        return None
    return df[list(_REQUIRED_COLS)]


# -- Public API ------------------------------------------------------------

def fetch_bhavcopy(d: date, skip_cache: bool = False) -> Optional[pd.DataFrame]:
    """
    Return a clean DataFrame for a single trading date, or None.
    Checks cache first; validates that response date matches request date.
    """
    if not skip_cache:
        cached = _load_cache(d)
        if cached is not None:
            return cached

    raw = _fetch_mcx_raw(d)
    if raw is None:
        return None

    normalised = _normalise_columns(raw)
    if normalised is None:
        return None

    # Filter to gold symbols only
    normalised["Symbol"] = normalised["Symbol"].apply(clean_symbol)
    gold = normalised[normalised["Symbol"].isin(GOLD_SYMBOLS)].copy()

    if gold.empty:
        log.info(f"MCX {d}: no gold rows found after filtering")
        return None

    # Validate response date matches request date
    gold, warns = validate_response_date(d, gold, date_col="Date")
    for w in warns:
        log.warning(w)

    if gold.empty:
        log.info(f"MCX {d}: all rows discarded after date validation (holiday?)")
        return None

    # Parse typed columns
    try:
        gold["Date"]         = gold["Date"].apply(lambda x: parse_response_date(str(x)))
        gold["ExpiryDate"]   = gold["ExpiryDate"].apply(lambda x: parse_expiry_date(str(x)))
        for col in ("Open", "High", "Low", "Close", "Volume", "OpenInterest"):
            gold[col] = pd.to_numeric(gold[col], errors="coerce")
    except Exception as e:
        log.error(f"MCX {d}: type conversion failed: {e}")
        return None

    gold, warns = validate_ohlcv(gold)
    for w in warns:
        log.warning(w)

    if gold.empty:
        return None

    # Key every contract by (Symbol, ExpiryDate)
    gold["contract_key"] = gold["Symbol"] + "_" + gold["ExpiryDate"].astype(str)

    _save_cache(d, gold)
    return gold


def fetch_date_range(
    start: date,
    end: date,
    skip_cache: bool = False,
    max_consecutive_failures: int = 3,
) -> tuple[pd.DataFrame, list[str], bool]:
    """
    Fetch all trading days in [start, end].
    Returns (combined_df, failure_log, success_flag).
    success_flag is True only if real data was successfully fetched.
    Fast-fails if max_consecutive_failures is reached (e.g. MCX 403 WAF blocks).
    """
    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    current = start
    consecutive_fails = 0

    while current <= end:
        log.info(f"Fetching {current} …")
        df = fetch_bhavcopy(current, skip_cache=skip_cache)
        if df is not None and not df.empty:
            frames.append(df)
            consecutive_fails = 0
        else:
            failures.append(str(current))
            consecutive_fails += 1
            if consecutive_fails >= max_consecutive_failures and len(frames) == 0:
                log.warning(
                    f"Reached {consecutive_fails} consecutive failures from MCX endpoint "
                    f"(HTTP 403 / WAF block / network). Triggering fast fallback to synthetic data."
                )
                break

        current += timedelta(days=1)
        # Only rate-limit non-cached requests
        if not _cache_path(current - timedelta(days=1)).exists():
            time.sleep(RATE_LIMIT_DELAY_S)

    if not frames:
        return pd.DataFrame(), failures, False

    combined = pd.concat(frames, ignore_index=True)
    log.info(
        f"Fetched {len(combined)} rows across "
        f"{combined['Date'].nunique()} trading days. "
        f"Failures: {len(failures)}"
    )
    return combined, failures, True


def load_local_raw_csvs(data_dir: Path = DATA_RAW) -> tuple[pd.DataFrame, int, int]:
    """
    Scan data_dir for *.csv BhavCopyDateWise files.

    Real MCX format:
      - Filename: BhavCopyDateWise_DDMMYYYY.csv  (e.g. BhavCopyDateWise_01102026.csv)
      - Date column:   "01 Oct 2026"  (DD Mon YYYY)
      - Expiry Date:   "30OCT2026"    (DDMONYYYY)
      - Symbol column: padded, e.g. "GOLDM        "
      - Instrument Name: "FUTCOM" (futures) or "OPTFUT" (options)

    Processing steps:
      1. Parse filename -> file_date (DDMMYYYY format)
      2. Normalise column names
      3. Keep only FUTCOM rows (drop CE / PE options)
      4. Keep only GOLDM / GOLDTEN / GOLDGUINEA / GOLDPETAL symbols
      5. Validate that every row's Date column matches file_date
      6. Parse ExpiryDate (DDMONYYYY), numeric OHLCV
      7. Key by (Symbol, ExpiryDate)

    Returns (combined_df, n_accepted, n_rejected).
    """
    import re
    from datetime import datetime

    csv_files = list(data_dir.glob("*.csv"))
    if not csv_files:
        return pd.DataFrame(), 0, 0

    frames: list[pd.DataFrame] = []
    accepted = 0
    rejected = 0

    for csv_path in sorted(csv_files):
        try:
            raw = pd.read_csv(csv_path)
            norm = _normalise_columns(raw)
            if norm is None:
                log.warning(f"[LOCAL CSV] {csv_path.name}: missing required columns -- rejected.")
                rejected += 1
                continue

            # -- Step 1: Extract file date from filename ---------------------
            # Primary format: BhavCopyDateWise_DDMMYYYY.csv
            file_date: Optional[date] = None
            compact_match = re.search(r"(\d{8})", csv_path.stem)
            if compact_match:
                ds = compact_match.group(1)
                for fmt in ("%d%m%Y", "%Y%m%d"):
                    try:
                        file_date = datetime.strptime(ds, fmt).date()
                        break
                    except ValueError:
                        pass
            if file_date is None:
                iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", csv_path.stem)
                if iso_match:
                    try:
                        file_date = datetime.strptime(iso_match.group(1), "%Y-%m-%d").date()
                    except ValueError:
                        pass

            # -- Step 2: Keep only futures (FUTCOM), drop options (OPTFUT) ---
            norm["InstrumentName"] = norm["InstrumentName"].str.strip().str.upper()
            futures = norm[norm["InstrumentName"] == _FUTCOM_NAME].copy()
            if futures.empty:
                log.warning(f"[LOCAL CSV] {csv_path.name}: no FUTCOM rows found -- rejected.")
                rejected += 1
                continue

            # -- Step 3: Filter to target gold symbols -----------------------
            futures["Symbol"] = futures["Symbol"].apply(clean_symbol)
            gold = futures[futures["Symbol"].isin(GOLD_SYMBOLS)].copy()
            if gold.empty:
                log.warning(f"[LOCAL CSV] {csv_path.name}: no target gold futures found -- rejected.")
                rejected += 1
                continue

            # -- Step 4: Validate Date column against filename date ----------
            if file_date is not None:
                # Real MCX Date format: "01 Oct 2026" (DD Mon YYYY)
                def _parse_mcx_date(s: str) -> date:
                    """Parse 'DD Mon YYYY' or fall back to response-date parser."""
                    s = s.strip()
                    for fmt in ("%d %b %Y", "%d %B %Y"):
                        try:
                            return datetime.strptime(s, fmt).date()
                        except ValueError:
                            pass
                    # Fallback: delegate to existing parser (handles MM/DD/YYYY)
                    return parse_response_date(s)

                parsed_dates = []
                for val in gold["Date"]:
                    try:
                        parsed_dates.append(_parse_mcx_date(str(val)))
                    except ValueError:
                        parsed_dates.append(date(1900, 1, 1))   # sentinel

                gold = gold.copy()
                gold["_parsed_date"] = parsed_dates
                mask = gold["_parsed_date"] == file_date
                n_bad = (~mask).sum()
                if n_bad > 0:
                    wrong = gold.loc[~mask, "_parsed_date"].unique().tolist()
                    log.warning(
                        f"[LOCAL CSV] {csv_path.name}: {n_bad} rows have Date {wrong} "
                        f"!= filename date {file_date} -- discarded."
                    )
                gold = gold[mask].drop(columns=["_parsed_date"]).reset_index(drop=True)
                if gold.empty:
                    log.warning(f"[LOCAL CSV] {csv_path.name}: all rows failed date validation -- rejected.")
                    rejected += 1
                    continue
                gold["Date"] = file_date
            else:
                # No date in filename -- parse the Date column directly
                def _parse_mcx_date_direct(s: str) -> date:
                    s = str(s).strip()
                    for fmt in ("%d %b %Y", "%d %B %Y"):
                        try:
                            return datetime.strptime(s, fmt).date()
                        except ValueError:
                            pass
                    return parse_response_date(s)
                gold["Date"] = gold["Date"].apply(_parse_mcx_date_direct)

            # -- Step 5: Parse ExpiryDate (30OCT2026 -> DDMONYYYY) -----------
            gold["ExpiryDate"] = gold["ExpiryDate"].apply(
                lambda x: parse_expiry_date(str(x)) if not isinstance(x, date) else x
            )

            # -- Step 6: Numeric OHLCV ---------------------------------------
            for col in ("Open", "High", "Low", "Close", "Volume", "OpenInterest"):
                gold[col] = pd.to_numeric(gold[col], errors="coerce")

            gold, warns = validate_ohlcv(gold)
            for w in warns:
                log.warning(w)
            if gold.empty:
                log.warning(f"[LOCAL CSV] {csv_path.name}: all rows failed OHLCV validation -- rejected.")
                rejected += 1
                continue

            # -- Step 7: Key by (Symbol, ExpiryDate) ------------------------
            gold["contract_key"] = gold["Symbol"] + "_" + gold["ExpiryDate"].astype(str)
            frames.append(gold)
            accepted += 1
            log.info(
                f"[LOCAL CSV] {csv_path.name}: accepted {len(gold)} rows "
                f"({gold['Symbol'].nunique()} symbols, date={file_date})"
            )
        except Exception as e:
            log.warning(f"[LOCAL CSV] Error reading {csv_path.name}: {e} -- rejected.")
            rejected += 1

    if not frames:
        return pd.DataFrame(), accepted, rejected

    combined = pd.concat(frames, ignore_index=True)
    log.info(
        f"[LOCAL CSV] Accepted {accepted} file(s), rejected {rejected}. "
        f"Total rows: {len(combined)}, trading days: {combined['Date'].nunique()}"
    )
    return combined, accepted, rejected

