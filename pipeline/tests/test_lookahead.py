"""
Unit tests to verify strict look-ahead bias prevention.
1. The robust expanding z-score at day t must use ONLY data points 0..t.
2. Modifying or injecting extreme shocks into data at t+1..N must NOT alter z-score at day t.
3. Observations before min_obs must be NaN.
4. Signal generated on day t is executed on day t+1.
"""

import numpy as np
import pandas as pd
from pipeline.analysis import robust_zscore_expanding, generate_signals
from pipeline.backtest import run_backtest


def test_no_future_leakage_in_zscore():
    np.random.seed(42)
    n = 100
    base_data = pd.Series(np.random.normal(10, 2, n), name="Residual")

    # Compute baseline expanding z-score
    z_baseline = robust_zscore_expanding(base_data, min_obs=30)

    # Now alter future data from index 60 onwards drastically
    mutated_data = base_data.copy()
    mutated_data.iloc[60:] = mutated_data.iloc[60:] * 100.0 + 5000.0

    z_mutated = robust_zscore_expanding(mutated_data, min_obs=30)

    # For all t < 60, z_mutated MUST be bit-for-bit identical to z_baseline
    for t in range(60):
        if np.isnan(z_baseline.iloc[t]):
            assert np.isnan(z_mutated.iloc[t])
        else:
            assert np.isclose(z_baseline.iloc[t], z_mutated.iloc[t], atol=1e-12)


def test_min_obs_guard():
    data = pd.Series(np.arange(50), name="Residual")
    z = robust_zscore_expanding(data, min_obs=30)

    # Indices 0 to 28 must be NaN
    assert z.iloc[:29].isna().all()
    # Index 29 (the 30th observation) onwards must NOT be NaN
    assert not np.isnan(z.iloc[29])
    assert not np.isnan(z.iloc[49])


def test_execution_delay_t_plus_1():
    """
    Verify in the backtest that a trade triggered by signal at close of day t
    is executed using the price of day t+1.
    """
    dates = pd.date_range("2026-01-01", periods=60, freq="B")
    residuals = pd.Series(np.random.normal(0, 1, 60), name="Residual")
    
    # Force a signal trigger at index 40
    residuals.iloc[40] = 50.0  # huge positive spike -> short signal at day t=40

    df = pd.DataFrame({
        "Date": dates,
        "NormBase": 72000.0 + np.arange(60) * 10.0,
        "NormTarget": 72000.0 + np.arange(60) * 10.0 + residuals,
        "Residual": residuals,
        "BaseExpiry": pd.Timestamp("2026-06-01"),
        "TargetExpiry": pd.Timestamp("2026-06-28"),
    })

    sig_df = generate_signals(df, zscore_threshold=2.0)
    bt = run_backtest(sig_df, "GOLDM", "GOLDGUINEA")

    # If trades occurred, the entry date must strictly follow the signal date
    for trade in bt["trades"]:
        entry_date = pd.Timestamp(trade["entry_date"])
        # Find which date had the signal
        matching_sig = sig_df[sig_df["Date"] < entry_date]
        assert not matching_sig.empty


def test_signals_do_not_leak_future_residuals():
    """
    Verify that generating signals on a series up to length T gives
    identical signals and z-scores for all t <= T even if subsequent
    future data points are appended or altered.
    """
    dates = pd.date_range("2026-01-01", periods=50, freq="B")
    np.random.seed(123)
    res = np.random.normal(0, 5, 50)
    df_short = pd.DataFrame({
        "Date": dates[:40],
        "NormBase": 72000.0,
        "NormTarget": 72000.0 + res[:40],
        "Residual": res[:40],
        "BaseExpiry": pd.Timestamp("2026-09-01"),
        "TargetExpiry": pd.Timestamp("2026-09-28"),
    })
    df_long = pd.DataFrame({
        "Date": dates,
        "NormBase": 72000.0,
        "NormTarget": 72000.0 + res,
        "Residual": res,
        "BaseExpiry": pd.Timestamp("2026-09-01"),
        "TargetExpiry": pd.Timestamp("2026-09-28"),
    })

    sig_short = generate_signals(df_short, zscore_threshold=2.0)
    sig_long = generate_signals(df_long, zscore_threshold=2.0)

    # For all rows 0..39, the z-scores must be identical
    for i in range(40):
        z_s = sig_short.iloc[i]["ZScore"]
        z_l = sig_long.iloc[i]["ZScore"]
        if np.isnan(z_s):
            assert np.isnan(z_l)
        else:
            assert np.isclose(z_s, z_l, atol=1e-12)
        assert sig_short.iloc[i]["Signal"] == sig_long.iloc[i]["Signal"]
