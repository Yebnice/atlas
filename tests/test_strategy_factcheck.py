import asyncio
import ast
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def frame(n=500, freq="h"):
    idx=pd.date_range("2025-01-01", periods=n, freq=freq, tz="UTC")
    x=np.linspace(100,120,n)
    return pd.DataFrame({"open":x,"high":x+1,"low":x-1,"close":x}, index=idx)

def frame_volume(n=500):
    df=frame(n); df["volume"]=100.0; return df

def test_strategy_lab_no_keyword_parser():
    s=(ROOT/"app"/"main.py").read_text()
    block=s[s.index('@app.post("/api/customer/strategy-lab/candidates")'):s.index('@app.post("/api/customer/strategy-lab/candidates/{candidate_id}/validate")')]
    assert "generate_strategy_draft" in block
    assert "text=req.prompt.lower()" not in block
    assert 'indicators":[k.upper()' not in block

def test_ai_schema_has_supported_strategy_family():
    from app.strategy_ai import AIStrategySpec
    raw={"version":"atlas-strategy-v1","title":"Test","summary":"A test strategy with explicit rules and risk controls.","asset":"crypto","symbols":["BTC/USDT:USDT"],"timeframes":["1h"],"direction":"LONG","strategy_family":"TREND","entry_conditions":[{"type":"trend","rule":"Price above the 200 EMA","timeframe":"1h"}],"exit_conditions":[{"type":"stop","rule":"Stop at 2 ATR","timeframe":"1h"}],"risk_per_trade":0.005,"stop_loss_atr":2,"take_profit_rr":2,"sessions":[],"assumptions":[],"validation_warnings":[],"requires_backtest":True,"requires_walk_forward":True,"execution_mode":"PAPER_SHADOW_ONLY","implementation_status":"ATLAS_SUPPORTED_FAMILY"}
    out=AIStrategySpec.model_validate(raw)
    assert out.strategy_family=="TREND"

def test_rsi_monotonic_up_is_100():
    from app.strategy_engine import _rsi
    close=pd.Series(np.arange(1,40,dtype=float))
    r=_rsi(close,14).dropna()
    assert float(r.iloc[-1])==100.0

def test_vwap_missing_volume_is_not_fabricated():
    from app.strategy_engine import strategy_signals
    s=strategy_signals(frame(600))
    assert not bool(s["vwap_available"].any())
    assert np.allclose(s["vwap_signal"].fillna(0),0)

def test_opening_range_not_available_before_session_hour_closes():
    from app.strategy_engine import strategy_signals
    idx=pd.date_range("2025-01-06 06:00", "2025-01-06 10:30", freq="15min", tz="UTC")
    x=np.arange(len(idx),dtype=float)+100
    df=pd.DataFrame({"open":x,"high":x+1,"low":x-1,"close":x,"volume":100},index=idx)
    s=strategy_signals(df)
    london=s["london_range_high"]
    # 08:00-09:00 local London in January is 08:00-09:00 UTC; range is only known after 09:00.
    assert london.loc["2025-01-06 08:45+00:00"] != london.loc["2025-01-06 08:45+00:00"]
    assert np.isfinite(float(london.loc["2025-01-06 09:00+00:00"]))

def test_higher_timeframe_mapping_applies_source_lag():
    from app.multi_timeframe import _map_back
    src=pd.Series([10.0,20.0], index=pd.to_datetime(["2025-01-01 01:00","2025-01-01 02:00"], utc=True))
    idx=pd.date_range("2025-01-01 00:30", periods=4, freq="30min", tz="UTC")
    out=_map_back(src,idx)
    # The 02:00 source value is not available at 02:00 itself under the conservative rule.
    assert out.loc["2025-01-01 02:00+00:00"]==10.0

def test_oos_gate_requires_forward_evidence():
    from app.research_engine import paper_candidates
    row={"strategy":"trend","sharpe":1.0,"max_drawdown":-0.1,"trades":40,"total_return":0.2}
    base={"strategies":[row],"validation":{"per_strategy_oos":{"trend":{"status":"OK","oos_total_return":0.1,"folds":[{"total_return":0.05},{"total_return":-0.01}]}}}}
    assert paper_candidates(base)
    bad={"strategies":[row],"validation":{"per_strategy_oos":{"trend":{"status":"OK","oos_total_return":-0.1,"folds":[{"total_return":0.05},{"total_return":-0.2}]}}}}
    assert paper_candidates(bad)==[]
