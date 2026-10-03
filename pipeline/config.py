"""
AuraSpread – Global configuration.
All tunable constants live here; no hard-coded values elsewhere.
"""

from pathlib import Path
from datetime import date, timedelta

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parent.parent
DATA_RAW    = ROOT / "data" / "raw"
DATA_PROC   = ROOT / "data" / "processed"
WEB_DATA    = ROOT / "web" / "data"

for _p in (DATA_RAW, DATA_PROC, WEB_DATA):
    _p.mkdir(parents=True, exist_ok=True)

# ── Date window ───────────────────────────────────────────────────────────
FETCH_END   = date.today()
FETCH_START = FETCH_END - timedelta(days=365)   # 12 months

# ── MCX Bhavcopy ──────────────────────────────────────────────────────────
MCX_URL     = "https://www.mcxindia.com/market-data/bhavcopy"
MCX_DATE_REQUEST_FMT  = "%d/%m/%Y"
MCX_DATE_RESPONSE_FMT = "%m/%d/%Y"
MCX_EXPIRY_FMT        = "%d%b%Y"   # e.g. 04SEP2026

# ── Contract definitions ──────────────────────────────────────────────────
CONTRACTS = {
    "GOLDM":       {"lot_size": 100, "quote_unit_g": 10, "purity": 995,
                    "listed_from": date(2000, 1, 1), "expiry_day_range": (3,  5)},
    "GOLDTEN":     {"lot_size":  10, "quote_unit_g": 10, "purity": 999,
                    "listed_from": date(2025, 1, 1), "expiry_day_range": (27, 31)},
    "GOLDGUINEA":  {"lot_size":   8, "quote_unit_g":  8, "purity": 999,
                    "listed_from": date(2000, 1, 1), "expiry_day_range": (27, 31)},
    "GOLDPETAL":   {"lot_size":   1, "quote_unit_g":  1, "purity": 999,
                    "listed_from": date(2000, 1, 1), "expiry_day_range": (27, 31)},
}

# Normalization target: INR per 10 g of 999 gold
NORM_UNIT_G  = 10
NORM_PURITY  = 999

# ── Analysis parameters ───────────────────────────────────────────────────
ZSCORE_MIN_OBS          = 30
ZSCORE_BUFFER_SIGMA     = 0.5

# Tender / expiry blackout
TENDER_BLACKOUT_DAYS    = 5
EXPIRY_BLACKOUT_DAYS    = 2

# ── Cost model parameters ─────────────────────────────────────────────────
COST_BROKERAGE_PCT      = 0.0002
COST_STT_PCT            = 0.0001
COST_EXCHANGE_CHARGE    = 0.002
SLIPPAGE_BASE           = 2.0
SLIPPAGE_THIN_MULT      = {
    "GOLDM":       1.0,
    "GOLDTEN":     2.0,
    "GOLDGUINEA":  3.0,
    "GOLDPETAL":   4.0,
}
THIN_VOLUME_LOTS        = {
    "GOLDM":       500,
    "GOLDTEN":     100,
    "GOLDGUINEA":  200,
    "GOLDPETAL":   1000,
}

# ── Backtest parameters ───────────────────────────────────────────────────
TRAIN_FRAC              = 0.60
MAX_LOTS_PER_TRADE      = 10

# ── HTTP / rate-limiting ──────────────────────────────────────────────────
REQUEST_TIMEOUT_S       = 30
RATE_LIMIT_DELAY_S      = 1.2
MAX_RETRIES             = 3

# ── Synthetic data seed ───────────────────────────────────────────────────
SYNTHETIC_SEED          = 42
