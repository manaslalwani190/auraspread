#!/usr/bin/env python3
"""
AuraSpread – download_bhavcopy.py
=================================
Bulk historical MCX Bhavcopy downloader.

Downloads daily Bhavcopy CSV files from MCX for a given date range,
saving them in the same format the pipeline already expects:
    data/raw/BhavCopyDateWise_DDMMYYYY.csv

Usage examples
--------------
# Download Aug–Sep 2026
python -m pipeline.download_bhavcopy --from 01/08/2026 --to 30/09/2026

# Download and immediately rerun the analysis pipeline
python -m pipeline.download_bhavcopy --from 01/08/2026 --to 30/09/2026 --run-pipeline

# Force re-download even if local files exist
python -m pipeline.download_bhavcopy --from 01/08/2026 --to 30/09/2026 --force

Features
--------
- Skips weekends automatically
- Skips known MCX holidays (pipeline/mcx_holidays.py)
- Skips dates where the output file already exists (unless --force)
- Primary source  : MCX BhavCopy datewise endpoint
- Fallback source : MCX alternate/archive endpoint + NSE commodity archive
- Rate limiting   : 1 s between requests (configurable with --delay)
- Per-date retry  : up to 3 attempts with 2 s back-off
- Saves failed dates to data/raw/failed_dates.txt
- Prints rich progress log + final summary
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Bootstrap: ensure project root is on sys.path so pipeline.* imports work
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.config import DATA_RAW, REQUEST_TIMEOUT_S
from pipeline.mcx_holidays import is_mcx_trading_day

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("auraspread.downloader")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_RETRIES    = 3
RETRY_DELAY_S  = 2      # seconds between retry attempts
DEFAULT_RATE_S = 1.0    # seconds between successful requests

# MCX primary endpoint (datewise BhavCopy download)
# The real MCX portal issues a POST to this URL and returns a CSV stream.
# We replicate the browser request as faithfully as possible.
MCX_PRIMARY_URL = (
    "https://www.mcxindia.com/backpage.aspx/GetBhavCopyData"
)
MCX_DOWNLOAD_URL = (
    "https://www.mcxindia.com/market-data/bhavcopy"
)

# Alternate MCX direct-download URL (older archive format)
MCX_ARCHIVE_URL = (
    "https://www.mcxindia.com/Common/BhavCopy"
)

# NSE commodity segment archive (as emergency fallback)
# NSE does not publish the same format, so this is a best-effort URL.
NSE_FALLBACK_URL = (
    "https://nsearchives.nseindia.com/archives/cmot/bhavcopy/fo"
)

# Minimum bytes for a response to be considered valid (sanity check)
_MIN_VALID_BYTES = 500

# ---------------------------------------------------------------------------
# Date utilities
# ---------------------------------------------------------------------------

def parse_cli_date(s: str) -> date:
    """Parse DD/MM/YYYY from CLI argument."""
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{s}'. Expected format: DD/MM/YYYY (e.g. 01/08/2026)"
        )


def filename_for_date(d: date) -> str:
    """Return the canonical MCX filename for a date."""
    return f"BhavCopyDateWise_{d.strftime('%d%m%Y')}.csv"


def output_path_for_date(d: date) -> Path:
    """Return the full output path for a date's Bhavcopy file."""
    return DATA_RAW / filename_for_date(d)


def trading_days_in_range(start: date, end: date) -> list[date]:
    """Return all MCX trading days (Mon-Fri, non-holiday) in [start, end]."""
    days = []
    current = start
    while current <= end:
        if is_mcx_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    return session


# ---------------------------------------------------------------------------
# Download strategies
# ---------------------------------------------------------------------------

def _try_mcx_primary(session: requests.Session, d: date) -> Optional[bytes]:
    """
    Attempt MCX primary datewise BhavCopy endpoint.
    MCX serves the file via a form POST that returns the CSV directly,
    or via a redirect to a file URL.
    We try both a GET and POST variant.
    """
    date_str = d.strftime("%d/%m/%Y")   # DD/MM/YYYY as MCX expects
    file_date = d.strftime("%d%m%Y")     # DDMMYYYY for direct file URL

    strategies = [
        # Strategy 1: Direct file download URL (most reliable when it works)
        {
            "method": "GET",
            "url": f"https://www.mcxindia.com/Common/BhavCopy/BhavCopyDateWise_{file_date}.csv",
            "params": None,
            "data": None,
            "referer": "https://www.mcxindia.com/market-data/bhavcopy",
        },
        # Strategy 2: API endpoint used by the MCX website JS
        {
            "method": "POST",
            "url": "https://www.mcxindia.com/backpage.aspx/GetBhavCopyData",
            "params": None,
            "data": {"startDate": date_str, "endDate": date_str},
            "referer": "https://www.mcxindia.com/market-data/bhavcopy",
        },
        # Strategy 3: Query-string GET on the bhavcopy page
        {
            "method": "GET",
            "url": "https://www.mcxindia.com/market-data/bhavcopy",
            "params": {"frmDt": date_str, "toDt": date_str},
            "data": None,
            "referer": "https://www.mcxindia.com/",
        },
    ]

    for strat in strategies:
        try:
            session.headers.update({"Referer": strat["referer"]})
            if strat["method"] == "GET":
                resp = session.get(
                    strat["url"],
                    params=strat.get("params"),
                    timeout=REQUEST_TIMEOUT_S,
                    allow_redirects=True,
                )
            else:
                resp = session.post(
                    strat["url"],
                    data=strat.get("data"),
                    timeout=REQUEST_TIMEOUT_S,
                    allow_redirects=True,
                )

            if resp.status_code != 200:
                log.debug(f"  [MCX-primary] HTTP {resp.status_code} for {strat['url']}")
                continue

            content = resp.content
            if len(content) < _MIN_VALID_BYTES:
                log.debug(f"  [MCX-primary] Response too small ({len(content)} bytes)")
                continue

            # Quick CSV sanity: should contain "Date" or "FUTCOM" or similar
            text_sample = content[:512].decode("utf-8", errors="replace")
            if any(kw in text_sample for kw in ("Date", "FUTCOM", "Symbol", "Open")):
                return content

            log.debug("  [MCX-primary] Content doesn't look like a BhavCopy CSV")

        except requests.RequestException as exc:
            log.debug(f"  [MCX-primary] Request error: {exc}")
            continue

    return None


def _try_mcx_archive(session: requests.Session, d: date) -> Optional[bytes]:
    """
    Fallback: try alternate MCX archive/mirror endpoints.
    """
    file_date = d.strftime("%d%m%Y")
    alt_urls = [
        # Some MCX URLs follow a slightly different path
        f"https://www.mcxindia.com/archives/bhavcopy/BhavCopyDateWise_{file_date}.csv",
        f"https://www.mcxindia.com/MarketData/BhavCopy/BhavCopyDateWise_{file_date}.csv",
    ]

    for url in alt_urls:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT_S, allow_redirects=True)
            if resp.status_code == 200 and len(resp.content) >= _MIN_VALID_BYTES:
                text_sample = resp.content[:512].decode("utf-8", errors="replace")
                if any(kw in text_sample for kw in ("Date", "FUTCOM", "Symbol", "Open")):
                    log.debug(f"  [MCX-archive] Success via {url}")
                    return resp.content
        except requests.RequestException:
            continue

    return None


def _try_nse_fallback(session: requests.Session, d: date) -> Optional[bytes]:
    """
    Emergency fallback: NSE commodity archives.
    NSE publishes bhavcopy for commodity derivatives, though the format
    differs from MCX. We attempt the download and return the raw bytes
    for manual inspection.
    """
    # NSE commodity bhavcopy uses DDMMMYYYY format (e.g. 01AUG2026)
    nse_date = d.strftime("%d%b%Y").upper()
    year_str = d.strftime("%Y")
    month_str = d.strftime("%b").upper()

    nse_urls = [
        f"https://nsearchives.nseindia.com/archives/cmot/bhavcopy/fo/fo{nse_date}bhav.csv",
        f"https://www.nseindia.com/content/fo/fo{nse_date}bhav.csv",
    ]

    for url in nse_urls:
        try:
            # NSE requires specific headers
            session.headers.update({
                "Referer": "https://www.nseindia.com/",
                "Host": "nsearchives.nseindia.com" if "archives" in url else "www.nseindia.com",
            })
            resp = session.get(url, timeout=REQUEST_TIMEOUT_S, allow_redirects=True)
            if resp.status_code == 200 and len(resp.content) >= _MIN_VALID_BYTES:
                log.debug(f"  [NSE-fallback] Success via {url}")
                return resp.content
        except requests.RequestException:
            continue

    return None


# ---------------------------------------------------------------------------
# Single-date download with retry
# ---------------------------------------------------------------------------

def download_date(
    session: requests.Session,
    d: date,
    force: bool = False,
    rate_delay: float = DEFAULT_RATE_S,
) -> tuple[str, Optional[Path]]:
    """
    Download BhavCopy for a single date.

    Returns
    -------
    (status, path)
      status : 'skipped_exists' | 'skipped_holiday' | 'downloaded' |
                'fallback_downloaded' | 'failed'
      path   : Path of saved file, or None on failure/skip
    """
    out_path = output_path_for_date(d)

    # Skip if already exists and not forcing re-download
    if out_path.exists() and not force:
        log.info(f"  [{d}] SKIP – already exists: {out_path.name}")
        return "skipped_exists", out_path

    log.info(f"  [{d}] Downloading…")

    content: Optional[bytes] = None
    source_label = "unknown"

    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            log.info(f"    Retry {attempt}/{MAX_RETRIES}…")
            time.sleep(RETRY_DELAY_S * (attempt - 1))

        # 1. MCX primary
        content = _try_mcx_primary(session, d)
        if content:
            source_label = "MCX-primary"
            break

        # 2. MCX archive
        content = _try_mcx_archive(session, d)
        if content:
            source_label = "MCX-archive"
            break

        # 3. NSE fallback (last resort)
        content = _try_nse_fallback(session, d)
        if content:
            source_label = "NSE-fallback"
            break

    if not content:
        log.warning(f"  [{d}] FAILED after {MAX_RETRIES} attempts")
        return "failed", None

    # Write file
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(content)
    size_kb = len(content) / 1024
    log.info(
        f"  [{d}] ✓ Saved {out_path.name} "
        f"({size_kb:.1f} KB, source={source_label})"
    )

    # Rate limit after each successful download
    time.sleep(rate_delay)

    status = "downloaded" if source_label.startswith("MCX") else "fallback_downloaded"
    return status, out_path


# ---------------------------------------------------------------------------
# Main bulk download function
# ---------------------------------------------------------------------------

def bulk_download(
    start: date,
    end: date,
    force: bool = False,
    rate_delay: float = DEFAULT_RATE_S,
    dry_run: bool = False,
) -> dict:
    """
    Download BhavCopy CSVs for all MCX trading days in [start, end].

    Returns a summary dict.
    """
    if start > end:
        raise ValueError(f"Start date {start} must be <= end date {end}")

    session = _make_session()

    all_trading_days = trading_days_in_range(start, end)
    total_calendar_days = (end - start).days + 1
    skipped_weekend = total_calendar_days - len(all_trading_days) - sum(
        1 for d in _iter_range(start, end) if not d.weekday() < 5
    )

    # Distinguish holiday skips vs weekend skips
    skipped_holidays = [
        d for d in _iter_range(start, end)
        if d.weekday() < 5 and d not in all_trading_days
    ]

    log.info("=" * 65)
    log.info("  AuraSpread – MCX Bhavcopy Bulk Downloader")
    log.info("=" * 65)
    log.info(f"  Date range    : {start} to {end}")
    log.info(f"  Calendar days : {total_calendar_days}")
    log.info(f"  Trading days  : {len(all_trading_days)}")
    log.info(f"  Holidays      : {len(skipped_holidays)}")
    log.info(f"  Output dir    : {DATA_RAW}")
    log.info(f"  Force re-dl   : {force}")
    if dry_run:
        log.info("  DRY RUN – no files will be written")
    log.info("=" * 65)

    if dry_run:
        log.info(f"\nWould download {len(all_trading_days)} file(s):")
        for d in all_trading_days:
            p = output_path_for_date(d)
            exists = "EXISTS" if p.exists() else "MISSING"
            log.info(f"  {d}  {p.name}  [{exists}]")
        return {"dry_run": True, "would_download": len(all_trading_days)}

    results = {
        "downloaded": [],
        "fallback_downloaded": [],
        "skipped_exists": [],
        "skipped_holidays": skipped_holidays,
        "failed": [],
    }

    total = len(all_trading_days)
    for idx, d in enumerate(all_trading_days, 1):
        log.info(f"\n[{idx:>4}/{total}] {d}")
        status, path = download_date(session, d, force=force, rate_delay=rate_delay)
        results[status].append(d)

    session.close()
    return results


def _iter_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


# ---------------------------------------------------------------------------
# Summary + failed-dates file
# ---------------------------------------------------------------------------

def print_summary(results: dict, start: date, end: date) -> None:
    """Print a rich summary table and save failed dates to disk."""
    downloaded       = results.get("downloaded", [])
    fallback_dl      = results.get("fallback_downloaded", [])
    skipped_exists   = results.get("skipped_exists", [])
    skipped_holidays = results.get("skipped_holidays", [])
    failed           = results.get("failed", [])

    total_new = len(downloaded) + len(fallback_dl)

    log.info("\n" + "=" * 65)
    log.info("  DOWNLOAD SUMMARY")
    log.info("=" * 65)
    log.info(f"  Date range requested    : {start} to {end}")
    log.info(f"  Files downloaded (MCX)  : {len(downloaded)}")
    log.info(f"  Files downloaded (fallback): {len(fallback_dl)}")
    log.info(f"  Files already existed   : {len(skipped_exists)}")
    log.info(f"  Holidays skipped        : {len(skipped_holidays)}")
    log.info(f"  FAILED downloads        : {len(failed)}")
    log.info("-" * 65)
    log.info(f"  TOTAL new files saved   : {total_new}")

    if skipped_exists:
        oldest = min(skipped_exists)
        newest = max(skipped_exists)
        log.info(f"  Already-existing range  : {oldest} → {newest}")

    if failed:
        failed_path = DATA_RAW / "failed_dates.txt"
        lines = [d.strftime("%d/%m/%Y") for d in sorted(failed)]
        failed_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.info(f"\n  Failed dates written to : {failed_path}")
        log.info("  Failed dates:")
        for d in sorted(failed):
            log.info(f"    {d}")

    log.info("=" * 65)


# ---------------------------------------------------------------------------
# --run-pipeline integration
# ---------------------------------------------------------------------------

def run_analysis_pipeline() -> None:
    """Invoke the main analysis pipeline after download."""
    log.info("\n[--run-pipeline] Launching analysis pipeline…")
    try:
        # Import here to avoid circular imports at module load time
        import importlib
        rp = importlib.import_module("pipeline.run_pipeline")
        if hasattr(rp, "main"):
            rp.main()
        else:
            # run_pipeline.py may be a script; run it as __main__
            import subprocess
            result = subprocess.run(
                [sys.executable, "-m", "pipeline.run_pipeline"],
                cwd=str(_PROJECT_ROOT),
                check=False,
            )
            if result.returncode != 0:
                log.error("Pipeline exited with non-zero code.")
    except Exception as exc:
        log.error(f"Pipeline failed: {exc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pipeline.download_bhavcopy",
        description="Bulk download MCX Bhavcopy CSVs for a date range.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download all of Aug 2026
  python -m pipeline.download_bhavcopy --from 01/08/2026 --to 31/08/2026

  # Download and rerun analysis
  python -m pipeline.download_bhavcopy --from 01/01/2025 --to 30/09/2026 --run-pipeline

  # Preview which dates would be downloaded (no HTTP calls)
  python -m pipeline.download_bhavcopy --from 01/08/2026 --to 31/08/2026 --dry-run

  # Force re-download even if files exist
  python -m pipeline.download_bhavcopy --from 01/10/2026 --to 01/10/2026 --force
""",
    )
    p.add_argument(
        "--from", dest="date_from", required=True, metavar="DD/MM/YYYY",
        help="Start date (inclusive), format: DD/MM/YYYY",
    )
    p.add_argument(
        "--to", dest="date_to", required=True, metavar="DD/MM/YYYY",
        help="End date (inclusive), format: DD/MM/YYYY",
    )
    p.add_argument(
        "--run-pipeline", action="store_true",
        help="After downloading, rerun the AuraSpread analysis pipeline.",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Re-download files that already exist locally.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be downloaded without making any HTTP calls.",
    )
    p.add_argument(
        "--delay", type=float, default=DEFAULT_RATE_S, metavar="SECONDS",
        help=f"Rate-limit delay between requests in seconds (default: {DEFAULT_RATE_S}).",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return p


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    start = parse_cli_date(args.date_from)
    end   = parse_cli_date(args.date_to)

    if start > end:
        parser.error(f"--from ({start}) must be before or equal to --to ({end})")

    results = bulk_download(
        start=start,
        end=end,
        force=args.force,
        rate_delay=args.delay,
        dry_run=args.dry_run,
    )

    if not results.get("dry_run"):
        print_summary(results, start, end)

        if args.run_pipeline:
            run_analysis_pipeline()


if __name__ == "__main__":
    main()
