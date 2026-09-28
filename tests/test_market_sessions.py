import pandas as pd
import numpy as np
from app.market_sessions import session_label, session_state
from app.strategy_engine import strategy_signals, strategy_signal


def _df(n=500):
    idx = pd.date_range("2026-01-05", periods=n, freq="1h", tz="UTC")
    base = 100 + np.linspace(0, 20, n) + 2*np.sin(np.arange(n)/8)
    return pd.DataFrame({"open":base, "high":base+1, "low":base-1, "close":base+0.2, "volume":1000}, index=idx)


def test_session_labels_are_dst_aware():
    assert session_label(pd.Timestamp("2026-01-05 08:00", tz="UTC")) == "LONDON"
    assert session_label(pd.Timestamp("2026-01-05 14:30", tz="UTC")) == "NEW_YORK"
    # Summer DST: London 08:00 BST is 07:00 UTC and New York 09:30 EDT is 13:30 UTC.
    assert session_label(pd.Timestamp("2026-07-06 07:00", tz="UTC")) == "LONDON"
    assert session_label(pd.Timestamp("2026-07-06 13:30", tz="UTC")) == "NEW_YORK"


def test_session_state_open_windows_are_local_exchange_times():
    idx = pd.date_range("2026-01-05 08:00", periods=8, freq="h", tz="UTC")
    s = session_state(idx)
    assert bool(s.loc[pd.Timestamp("2026-01-05 08:00", tz="UTC"), "london_open_window"])
    assert bool(s.loc[pd.Timestamp("2026-01-05 14:00", tz="UTC"), "new_york_open_window"]) is False


def test_strategy_exposes_session_entry_exit_context():
    df = _df()
    s = strategy_signals(df)
    for col in ["adx", "rsi", "macd_signal", "vwap_signal", "london_open_breakout", "new_york_open_breakout", "session"]:
        assert col in s.columns
    result = strategy_signal(df)
    assert "entry_rule" in result and "exit_rule" in result
