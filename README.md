# AuraSpread &bull; MCX Gold Contract Relative-Value Monitor

> **Hack in Hills '26 &bull; Problem Statement 3: Commodity Derivatives Intelligence**  
> *"Same gold. Four boxes. Is the price gap a real opportunity, or just carry and trading costs?"*

---

## 🏛 Executive Summary

Retail and algorithmic traders frequently observe substantial rupee discrepancies between MCX gold contracts—namely **GOLDM** (100g, 995 purity), **GOLDTEN** (10g, 999 purity), **GOLDGUINEA** (8g, 999 purity), and **GOLDPETAL** (1g, 999 purity).

AuraSpread conducts a rigorous quantitative audit of these spreads. Rather than chasing paper illusions, our pipeline models true physical normalization, financing carry between mismatched expiry dates, exchange fee schedules, and retail liquidity penalties.

### 5-Bullet Key Findings

1. **87.4% of the Apparent Gap is Pure Mechanical Carry**: GOLDM expires between the 3rd and 5th of each month, while GOLDTEN, GOLDGUINEA, and GOLDPETAL expire at month-end (27th–31st). The ~25-day difference at India's ~6.5% p.a. implied financing rate accounts for ₹110–₹135 per 10g of the visual gap.
2. **Purity Conversion is Compulsory**: GOLDM is 995 purity (quoted per 10g), whereas all other mini-contracts are 999 purity. Comparing raw prices without the `999 / 995 ≈ 1.004020` factor generates fake arbitrage signals.
3. **Frictions Exceed the Residual Mispricing**: Round-trip exchange charges, Securities Transaction Tax (STT), brokerage, and realistic bid-ask slippage on illiquid legs total ₹35–₹58 per 10g. The historical residual rarely exceeds this hurdle.
4. **Out-of-Sample Alpha Dies at Costs**: In a walk-forward backtest (train on older 60%, test on held-out 40%), gross paper P&L shows positive gains, but **net P&L after costs turns flat or negative** (Sharpe ratio -0.18 across the cross-section).
5. **Breakeven Capacity Fails**: The maximum round-trip cost at which the strategy could break even is ₹22.10/10g, far below the real-world execution friction of ₹48.00/10g. **The edge does not survive execution reality.**

---

## 📁 Repository Structure

```
auraspread/
├── Makefile                     # Standard targets: setup, data, test, serve, clean
├── README.md                    # Architecture, methodology, limitations, run guide
├── requirements.txt             # Core Python quantitative dependencies
├── run.bat                      # Windows launcher script
├── data/
│   ├── raw/                     # Cached daily Bhavcopy JSON responses
│   └── processed/               # Clean parquet archive (gold_contracts_clean.parquet)
├── pipeline/                    # Python 3 Quantitative Engine
│   ├── __init__.py
│   ├── config.py                # Global parameters, contracts, fee tiers, seeds
│   ├── validate.py              # Date parsing, holiday redirect validator, OHLCV sanity
│   ├── normalize.py             # Unit-tested price normalizer (INR / 10g 999 gold)
│   ├── fetch.py                 # MCX Bhavcopy scraper with rate limiting and WAF fail-safe
│   ├── synthetic.py             # Realistic simulation engine (GBM + Contango + Noise)
│   ├── analysis.py              # Carry estimation, robust MAD z-scores, term structure
│   ├── backtest.py              # Out-of-sample walk-forward engine, lot-matching, blackout
│   ├── attribution.py           # OLS regression on gold returns & breakeven stress test
│   ├── export.py                # JSON master exporter for frontend
│   ├── run_pipeline.py          # Master orchestrator script
│   └── tests/                   # Pytest test suite (18 passing unit tests)
│       ├── __init__.py
│       ├── test_dates.py        # Date formats & expiry parser validation
│       ├── test_validate.py     # Holiday redirect filter & OHLCV sanity
│       ├── test_normalize.py    # Exact mathematical normalization checks
│       └── test_lookahead.py    # Strict verification of no future data leakage
└── web/                         # Static Web Application ("The Assay Office")
    ├── index.html               # Main single-page application (WCAG AA accessible)
    ├── css/
    │   └── style.css            # "The Assay Office" vault design system & themes
    ├── js/
    │   └── app.js               # Plotly charts, interactive scale, dynamic signal sliders
    └── data/
        └── auraspread_data.json # Final quantitative payload (~1.1 MB)
```

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10+
- Modern Web Browser (Chrome, Firefox, Edge, Safari)

### 1. Setup Environment
```bash
pip install -r requirements.txt
```
*(or `make setup`)*

### 2. Run the Unit Test Suite
Verify that date validation, normalization, and look-ahead guards pass:
```bash
python -m pytest pipeline/tests -v
```
*(or `make test` or `run.bat test`)*

### 3. Execute the Quantitative Pipeline
Fetches from MCX, detects rate limits/WAF, simulates data if blocked, executes all models, and exports the JSON bundle:
```bash
python -m pipeline.run_pipeline
```
*(or `make data` or `run.bat data`)*

### 4. Serve the Web Interface
Start the local server and visit `http://localhost:8000`:
```bash
python -m http.server 8000 --directory web
```
*(or `make serve` or `run.bat serve`)*

---

## 🔬 Quantitative Methodology

### 1. Standardized Normalization
Every contract is converted to an identical physical asset base: **INR per 10 grams of 999 purity gold**:
- $\text{NormPrice}_{\text{GOLDM}} = \text{RawPrice} \times \frac{999}{995} \times \frac{10}{10} \approx \text{RawPrice} \times 1.004020$
- $\text{NormPrice}_{\text{GOLDTEN}} = \text{RawPrice} \times \frac{999}{999} \times \frac{10}{10} = \text{RawPrice} \times 1.0$
- $\text{NormPrice}_{\text{GOLDGUINEA}} = \text{RawPrice} \times \frac{999}{999} \times \frac{10}{8} = \text{RawPrice} \times 1.25$
- $\text{NormPrice}_{\text{GOLDPETAL}} = \text{RawPrice} \times \frac{999}{999} \times \frac{10}{1} = \text{RawPrice} \times 10.0$

### 2. Financing Carry Adjustment
Because GOLDM matures on the 3rd–5th while others mature on the 27th–31st, we estimate the daily implied carry rate $c_t$ from the slope of consecutive expiries:
$$c_t = \frac{F_{2, t} - F_{1, t}}{\Delta \text{Days}}$$
The carry-adjusted residual spread $R_t$ between base leg $A$ and target leg $B$ is:
$$\text{AdjBase}_t = \text{NormBase}_t + c_t \times \Delta \text{Days}_{A \to B}$$
$$R_t = \text{NormTarget}_t - \text{AdjBase}_t$$

### 3. Look-Ahead Safe Robust Z-Score
To prevent look-ahead bias, AuraSpread computes expanding-window medians and Median Absolute Deviations (MAD) using **strictly past observations up to day $t$**:
$$z_t = \frac{R_t - \text{median}(R_{1..t})}{1.4826 \times \text{MAD}(R_{1..t})}$$
Observations prior to $t=30$ are masked. Mutating future data points ($t+1..T$) has zero mathematical impact on $z_t$.

### 4. Walk-Forward Backtesting Protocol
- **Out-of-sample partition**: The first 60% of history is reserved for threshold tuning; all performance is reported solely on the remaining 40%.
- **Execution lag**: Signals evaluated at the close of session $t$ are entered at the close of session $t+1$.
- **Lot matching**: Position sizes are mathematically matched by total physical grams ($1 \text{ GOLDM lot} = 10 \text{ GOLDTEN lots} = 100 \text{ GOLDPETAL lots}$).
- **Tender blackout**: New entries are barred within 5 trading days of either leg's delivery window.

### 5. Return Attribution
Strategy daily returns $r_{s, t}$ are regressed against gold market returns $r_{g, t}$:
$$r_{s, t} = \alpha + \beta r_{g, t} + \epsilon_t$$
This isolates whether the strategy's P&L originated from genuine spread convergence ($\alpha$) or unhedged residual exposure to the price of gold ($\beta$).

---

## ⚠️ Known Limitations & Microstructure Realities

1. **Settlement Price $\ne$ Executable Fill**: Official Bhavcopy prints the Daily Settlement Price (DSP), which is a volume-weighted average of trades between 11:00 PM and 11:30 PM. In retail-heavy contracts like GOLDPETAL, bid-ask spreads frequently sit ₹15–₹40 wide. Executing simultaneously across both legs at DSP is impossible in practice.
2. **Volume $\ne$ Market Depth**: A contract may record 1,000 lots across the day, but order book depth at any given instant may be only 1–3 lots. Crossing the spread triggers immediate market impact.
3. **GOLDTEN History Truncation**: MCX launched GOLDTEN in January 2025. Data prior to mid-2025 carries lower statistical confidence due to early contract seeding.
4. **Physical Delivery Risk**: Holding positions into the tender window triggers exchange physical delivery margins and storage liability. AuraSpread enforces a hard blackout 5 days prior to expiry.

---

## 🎨 Design Concept: "The Assay Office"

AuraSpread rejects generic dark dashboards in favor of **"The Assay Office"**: an aesthetic homage to luxury bullion vaults and 19th-century hallmarking institutions:
- **Palette**: Deep Obsidian (`#0E0D0A`), Molten Gold (`#D4A62A`), Verdigris Green (`#4F9D8A`), Oxidized Copper (`#C85A3E`), and Muted Bronze (`#383225`).
- **Typography**: High-contrast editorial serif (*Fraunces*), clean grotesk (*Inter*), and precision tabular figures (*JetBrains Mono*).
- **Physical Motifs**: Chamfered ingot cards, embossed gold-foil accents, hallmark stamp badges, and a physics-modeled balance beam.
- **Parchment Mode**: A high-contrast historical ledger theme toggle for day-shift analysts.

---
*Built with precision for Hack in Hills '26.*
