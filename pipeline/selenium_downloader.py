#!/usr/bin/env python3
"""
AuraSpread – selenium_downloader.py
===================================
Automated historical MCX Bhavcopy downloader using Selenium & real Chrome.

Bypasses direct HTTP/Akamai blocks by driving a real Chrome browser instance
against https://www.mcxindia.com/market-data/bhavcopy.

Features:
  - Real Chrome browser (non-headless by default for anti-bot compliance)
  - Automatic ChromeDriver management via webdriver-manager
  - Datepicker selection & CSV export automation
  - Skips weekends and known MCX trading holidays (mcx_holidays.py)
  - Skips already downloaded files (resumable)
  - Tracks progress in data/raw/selenium_progress.json
  - Staging download directory with atomic file moves to data/raw/
  - Random 5-10s delay between downloads to stay under rate-limits
  - Clean Ctrl+C handling with graceful browser shutdown
  - Optional --run-pipeline flag to trigger analysis after download

Usage:
  # Quick test for 5 dates:
  python pipeline/selenium_downloader.py --from 01/08/2026 --to 05/08/2026

  # Full historical range:
  python pipeline/selenium_downloader.py --from 01/01/2004 --to 03/10/2026

  # Force re-download of existing files:
  python pipeline/selenium_downloader.py --from 01/08/2026 --to 05/08/2026 --force
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Bootstrap: ensure project root is on sys.path
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.config import DATA_RAW
from pipeline.mcx_holidays import is_mcx_trading_day

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("auraspread.selenium")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MCX_BHAVCOPY_URL = "https://www.mcxindia.com/market-data/bhavcopy"
PROGRESS_FILE = DATA_RAW / "selenium_progress.json"
STAGING_DIR = DATA_RAW / ".selenium_staging"
FAILED_DATES_FILE = DATA_RAW / "failed_dates.txt"
MIN_VALID_BYTES = 100


def parse_cli_date(s: str) -> date:
    """Parse DD/MM/YYYY from CLI argument."""
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{s}'. Expected format: DD/MM/YYYY (e.g. 01/08/2026)"
        )


def canonical_filename(d: date) -> str:
    """Return canonical MCX bhavcopy filename."""
    return f"BhavCopyDateWise_{d.strftime('%d%m%Y')}.csv"


def output_path_for_date(d: date) -> Path:
    """Return destination path in data/raw/."""
    return DATA_RAW / canonical_filename(d)


def is_file_downloaded(d: date) -> bool:
    """Check if valid bhavcopy file already exists in data/raw/."""
    p = output_path_for_date(d)
    return p.is_file() and p.stat().st_size >= MIN_VALID_BYTES


def load_progress() -> dict:
    """Load progress metadata JSON if it exists."""
    if PROGRESS_FILE.is_file():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"completed_dates": [], "failed_dates": [], "no_data_dates": []}


def save_progress(progress: dict) -> None:
    """Persist progress to data/raw/selenium_progress.json."""
    try:
        progress["last_updated"] = datetime.now().isoformat()
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2)
    except Exception as e:
        log.warning("Could not save progress file: %s", e)


def record_failed_date(d: date, reason: str) -> None:
    """Append a failed date with reason to failed_dates.txt."""
    try:
        with open(FAILED_DATES_FILE, "a", encoding="utf-8") as f:
            f.write(f"{d.strftime('%d/%m/%Y')} - {reason}\n")
    except Exception as e:
        log.warning("Could not write to failed_dates.txt: %s", e)


def build_trading_calendar(start: date, end: date) -> list[date]:
    """Return all MCX trading dates (Mon-Fri, non-holiday) in [start, end]."""
    days = []
    curr = start
    while curr <= end:
        if is_mcx_trading_day(curr):
            days.append(curr)
        curr += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Selenium Driver Factory
# ---------------------------------------------------------------------------

def create_chrome_driver(headless: bool = False):
    """Initialize Chrome browser configured for downloading CSVs to staging."""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")

    # Anti-bot detection mitigation
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,800")

    # Download prefs: save straight into STAGING_DIR without prompt
    prefs = {
        "download.default_directory": str(STAGING_DIR.resolve()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        # Fall back to default system chromedriver if manager fails
        driver = webdriver.Chrome(options=options)

    # Further mask selenium flags
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"}
        )
    except Exception:
        pass

    return driver


# ---------------------------------------------------------------------------
# Core Downloader Engine
# ---------------------------------------------------------------------------

def wait_for_staging_download(timeout_s: float = 15.0) -> Optional[Path]:
    """Poll STAGING_DIR until a new non-crdownload file is ready."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(0.5)
        files = list(STAGING_DIR.glob("*"))
        # Exclude temporary download files
        ready = [
            f for f in files
            if not f.name.endswith(".crdownload")
            and not f.name.endswith(".tmp")
            and f.is_file()
        ]
        if ready:
            # Sort newest first
            ready.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            candidate = ready[0]
            if candidate.stat().st_size >= MIN_VALID_BYTES:
                return candidate
    return None


def filter_gold_csv(csv_path: Path) -> bool:
    """Filter CSV in-place to retain only gold futures contracts (FUTCOM)."""
    try:
        import pandas as pd
        df = pd.read_csv(csv_path)
        sym_col = next((c for c in df.columns if "symbol" in c.lower()), None)
        if sym_col is None:
            return False

        # Filter for Symbol containing GOLD
        mask = df[sym_col].astype(str).str.contains("GOLD", case=False, na=False)

        # Drop options (OPTFUT) and retain only futures (FUTCOM)
        inst_col = next((c for c in df.columns if "instrument" in c.lower()), None)
        if inst_col:
            mask = mask & (df[inst_col].astype(str).str.strip().str.upper() == "FUTCOM")
        else:
            opt_col = next((c for c in df.columns if "option" in c.lower()), None)
            if opt_col:
                mask = mask & df[opt_col].astype(str).str.strip().isin(["-", "", "nan", "None"])

        gold_df = df[mask]
        gold_df.to_csv(csv_path, index=False)
        return True
    except Exception as e:
        log.warning("Could not filter gold rows for %s: %s", csv_path.name, e)
        return False


def clean_staging_dir() -> None:
    """Clear any remaining files in staging directory."""
    if STAGING_DIR.exists():
        for f in STAGING_DIR.glob("*"):
            try:
                if f.is_file():
                    f.unlink()
            except Exception:
                pass


def download_date_via_selenium(
    driver,
    d: date,
    retry_count: int = 2
) -> tuple[bool, str]:
    """
    Download bhavcopy for single date using the active Selenium session.

    Returns:
      (success: bool, status_message: str)
    """
    date_str = d.strftime("%d/%m/%Y")
    dest_path = output_path_for_date(d)

    for attempt in range(1, retry_count + 1):
        clean_staging_dir()

        try:
            # 1. Ensure we are on the MCX Bhavcopy page
            if "mcxindia.com/market-data/bhavcopy" not in driver.current_url.lower():
                driver.get(MCX_BHAVCOPY_URL)
                time.sleep(4)

            # 2. Set the date picker value using jQuery / DOM
            set_date_script = f"""
                var el = $('#bhavCopyDateWise');
                if (el.length > 0) {{
                    el.val('{date_str}');
                    try {{ el.datepicker('setDate', '{date_str}'); }} catch(e) {{}}
                    el.trigger('change');
                    return true;
                }}
                var plain = document.getElementById('bhavCopyDateWise');
                if (plain) {{
                    plain.value = '{date_str}';
                    plain.dispatchEvent(new Event('change'));
                    return true;
                }}
                return false;
            """
            found_input = driver.execute_script(set_date_script)
            if not found_input:
                driver.get(MCX_BHAVCOPY_URL)
                time.sleep(4)
                driver.execute_script(set_date_script)

            time.sleep(0.5)

            # 3. Click the 'Show' button (id="btnDateWise") to query data
            click_show_script = """
                var btn = $('#btnDateWise');
                if (btn.length > 0) {
                    btn[0].click();
                    return true;
                }
                var plain = document.getElementById('btnDateWise');
                if (plain) {
                    plain.click();
                    return true;
                }
                return false;
            """
            driver.execute_script(click_show_script)

            # Wait for data fetch response (dynamic check via jQuery.active)
            for _ in range(20):
                time.sleep(0.5)
                try:
                    idle = driver.execute_script("return (!window.jQuery || jQuery.active === 0);")
                    if idle:
                        break
                except Exception:
                    pass
            time.sleep(1.0)

            # 4. Check if page indicates "No Record Found" or similar
            page_text = driver.execute_script("return document.body.innerText || '';")
            if "no record found" in page_text.lower() or "no data found" in page_text.lower():
                # Market was closed or no contracts traded on this date
                return False, "NO_DATA"

            # 5. Click the CSV download button (id="btnDateWiseCSV")
            click_csv_script = """
                var btn = $('#btnDateWiseCSV');
                if (btn.length > 0) {
                    btn[0].click();
                    return true;
                }
                var plain = document.getElementById('btnDateWiseCSV');
                if (plain) {
                    plain.click();
                    return true;
                }
                return false;
            """
            driver.execute_script(click_csv_script)

            # 6. Wait for file to land in STAGING_DIR
            downloaded_file = wait_for_staging_download(timeout_s=12.0)

            if downloaded_file and downloaded_file.stat().st_size >= MIN_VALID_BYTES:
                # Filter immediately to keep only GOLD rows, saving ~99% disk space
                filter_gold_csv(downloaded_file)
                # Move atomically to final destination
                shutil.move(str(downloaded_file), str(dest_path))
                clean_staging_dir()
                return True, "SUCCESS"


            # If no file downloaded, maybe it needs a retry or the page hung
            if attempt < retry_count:
                log.info("Retry %d/%d for %s...", attempt + 1, retry_count, date_str)
                driver.refresh()
                time.sleep(3)

        except Exception as ex:
            log.warning("Exception on %s (attempt %d): %s", date_str, attempt, ex)
            if attempt < retry_count:
                try:
                    driver.get(MCX_BHAVCOPY_URL)
                    time.sleep(4)
                except Exception:
                    pass

    return False, "TIMEOUT_OR_EMPTY"


# ---------------------------------------------------------------------------
# Runner & CLI
# ---------------------------------------------------------------------------

def run_selenium_downloader(
    start_date: date,
    end_date: date,
    force: bool = False,
    delay_min: float = 5.0,
    delay_max: float = 10.0,
    headless: bool = False,
    run_pipeline_after: bool = False,
) -> None:
    """Run full Selenium-based historical downloader workflow."""
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    trading_days = build_trading_calendar(start_date, end_date)
    total_trading_days = len(trading_days)

    print("=" * 68)
    print(" AuraSpread – MCX Historical Bhavcopy Selenium Downloader")
    print("=" * 68)
    print(f" Date range    : {start_date.strftime('%d/%m/%Y')} -> {end_date.strftime('%d/%m/%Y')}")
    print(f" Trading days  : {total_trading_days} (skipping weekends & MCX holidays)")
    print(f" Target folder : {DATA_RAW}")
    print(f" Rate delay    : {delay_min:.1f}s - {delay_max:.1f}s between requests")
    print(f" Mode          : {'Headless' if headless else 'Real Chrome Browser'}")
    print("=" * 68)

    if not trading_days:
        print("No trading days in specified date range.")
        return

    progress = load_progress()
    completed_set = set(progress.get("completed_dates", []))
    no_data_set = set(progress.get("no_data_dates", []))

    # Pre-check already existing files
    existing_count = 0
    to_download: list[date] = []

    for d in trading_days:
        d_str = d.strftime("%d/%m/%Y")
        if not force and is_file_downloaded(d):
            existing_count += 1
            completed_set.add(d_str)
        elif not force and d_str in no_data_set:
            existing_count += 1
        else:
            to_download.append(d)

    print(f" Already downloaded (skipped): {existing_count}")
    print(f" Remaining to fetch          : {len(to_download)}")
    print("-" * 68)

    if not to_download:
        print("All trading days in range are already downloaded! Nothing to do.")
        if run_pipeline_after:
            _trigger_pipeline()
        return

    print("Launching Chrome browser...")
    driver = create_chrome_driver(headless=headless)

    downloaded_count = 0
    failed_dates: list[date] = []
    new_no_data: list[date] = []

    try:
        log.info("Navigating to MCX Bhavcopy portal...")
        driver.get(MCX_BHAVCOPY_URL)
        time.sleep(5)

        total_to_process = len(to_download)

        for idx, d in enumerate(to_download, 1):
            d_str = d.strftime("%d/%m/%Y")

            success, status = download_date_via_selenium(driver, d)

            if success:
                downloaded_count += 1
                completed_set.add(d_str)
                progress["completed_dates"] = sorted(list(completed_set))
                save_progress(progress)
                print(f"Downloaded {d_str} ({idx}/{total_to_process})")
            elif status == "NO_DATA":
                new_no_data.append(d)
                no_data_set.add(d_str)
                progress["no_data_dates"] = sorted(list(no_data_set))
                save_progress(progress)
                print(f"No Data for {d_str} (market closed / holiday) ({idx}/{total_to_process})")
            else:
                failed_dates.append(d)
                record_failed_date(d, status)
                print(f"Failed     {d_str} [{status}] ({idx}/{total_to_process})")

            # Respectful rate-limiting wait between dates
            if idx < total_to_process:
                delay = random.uniform(delay_min, delay_max)
                time.sleep(delay)

    except KeyboardInterrupt:
        print("\n\nProcess interrupted by user (Ctrl+C). Saving progress...")
    finally:
        clean_staging_dir()
        try:
            driver.quit()
        except Exception:
            pass
        save_progress(progress)

    # -----------------------------------------------------------------------
    # Final Summary Report
    # -----------------------------------------------------------------------
    print("\n" + "=" * 68)
    print(" Download Session Summary")
    print("=" * 68)
    print(f" Date range covered    : {start_date.strftime('%d/%m/%Y')} -> {end_date.strftime('%d/%m/%Y')}")
    print(f" Total trading days    : {total_trading_days}")
    print(f" Previously existing   : {existing_count}")
    print(f" Newly downloaded      : {downloaded_count}")
    print(f" No data / closed      : {len(new_no_data)}")
    print(f" Failed dates          : {len(failed_dates)}")

    if failed_dates:
        print(f"\nFailed dates have been logged to: {FAILED_DATES_FILE}")
        for fd in failed_dates[:10]:
            print(f"  - {fd.strftime('%d/%m/%Y')}")
        if len(failed_dates) > 10:
            print(f"  ... and {len(failed_dates) - 10} more")
    print("=" * 68 + "\n")

    if run_pipeline_after:
        _trigger_pipeline()


def _trigger_pipeline() -> None:
    """Run pipeline.run_pipeline if requested."""
    print("Triggering analysis pipeline...")
    try:
        from pipeline.run_pipeline import run_pipeline
        run_pipeline()
    except Exception as e:
        log.error("Pipeline run encountered an error: %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AuraSpread MCX Selenium Bhavcopy Downloader",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        type=parse_cli_date,
        default=parse_cli_date("01/01/2004"),
        help="Start date in DD/MM/YYYY format",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        type=parse_cli_date,
        default=parse_cli_date("03/10/2026"),
        help="End date in DD/MM/YYYY format",
    )
    parser.add_argument(
        "--delay-min",
        type=float,
        default=5.0,
        help="Minimum random delay (seconds) between dates",
    )
    parser.add_argument(
        "--delay-max",
        type=float,
        default=10.0,
        help="Maximum random delay (seconds) between dates",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force redownload even if local file exists",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless Chrome mode (default is visible real browser)",
    )
    parser.add_argument(
        "--run-pipeline",
        action="store_true",
        help="Rerun the AuraSpread pipeline after download completes",
    )

    args = parser.parse_args()

    if args.from_date > args.to_date:
        parser.error(f"--from date ({args.from_date}) must be <= --to date ({args.to_date})")

    run_selenium_downloader(
        start_date=args.from_date,
        end_date=args.to_date,
        force=args.force,
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        headless=args.headless,
        run_pipeline_after=args.run_pipeline,
    )


if __name__ == "__main__":
    main()
