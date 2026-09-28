import asyncio
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_strategy_ai_module_parses():
    ast.parse((ROOT / "app" / "strategy_ai.py").read_text())


def test_strategy_ai_requires_real_provider(monkeypatch):
    import app.strategy_ai as sai
    monkeypatch.setattr(sai.settings, "gemini_api_key", "")
    monkeypatch.setattr(sai.settings, "groq_api_key", "")
    with pytest.raises(sai.AIProviderError, match="No AI strategy provider"):
        asyncio.run(sai.generate_strategy_draft(prompt="Build a trend strategy for BTC using 1h confirmation", name="Test"))


def test_strategy_ai_validates_and_caps_risk(monkeypatch):
    import app.strategy_ai as sai
    monkeypatch.setattr(sai.settings, "gemini_api_key", "configured")
    monkeypatch.setattr(sai.settings, "groq_api_key", "")
    monkeypatch.setattr(sai.settings, "risk_per_trade", 0.005)

    async def fake(prompt, **kwargs):
        return {
            "version": "atlas-strategy-v1",
            "title": "BTC Trend",
            "summary": "Trend-following strategy with explicit confirmation and exits.",
            "asset": "crypto",
            "symbols": ["BTC/USDT:USDT"],
            "timeframes": ["1h"],
            "direction": "LONG",
            "strategy_family": "TREND",
            "entry_conditions": [{"type": "trend", "rule": "Price above the 200 EMA", "timeframe": "1h"}],
            "exit_conditions": [{"type": "stop", "rule": "Stop at 2 ATR", "timeframe": "1h"}],
            "risk_per_trade": 0.02,
            "stop_loss_atr": 2.0,
            "take_profit_rr": 2.0,
            "sessions": [],
            "assumptions": [],
            "validation_warnings": [],
            "requires_backtest": True,
            "requires_walk_forward": True,
            "execution_mode": "PAPER_SHADOW_ONLY",
            "implementation_status": "ATLAS_SUPPORTED_FAMILY",
        }

    monkeypatch.setattr(sai, "_gemini_json", fake)
    out = asyncio.run(sai.generate_strategy_draft(prompt="Build a BTC trend strategy", name="Test"))
    assert out["ai"]["provider"] == "gemini"
    assert out["ai"]["execution_authority"] is False
    assert out["strategy"]["risk_per_trade"] == 0.005
    assert out["strategy"]["execution_mode"] == "PAPER_SHADOW_ONLY"
    assert out["strategy"]["validation_warnings"]


def test_strategy_endpoint_no_longer_contains_keyword_parser():
    s = (ROOT / "app" / "main.py").read_text()
    start = s.index('@app.post("/api/customer/strategy-builder")')
    end = s.index('@app.get("/api/customer/strategy-builder")', start)
    block = s[start:end]
    # The builder endpoint now delegates to the Strategy Lab creation path (so drafts are
    # validatable instead of orphaned); that shared path is what calls the real AI model.
    assert "create_strategy_candidate(" in block
    lab_start = s.index('async def create_strategy_candidate')
    lab_end = s.index('@app.post("/api/customer/strategy-lab/candidates/{candidate_id}/validate")', lab_start)
    assert "generate_strategy_draft" in s[lab_start:lab_end]
    assert 'text=req.prompt.lower()' not in block
    assert 'indicators=[k.upper()' not in block


def test_strategy_deployment_wires_real_ai_secrets():
    deploy = (ROOT / "deploy" / "cloud-run-deploy.sh").read_text()
    bootstrap = (ROOT / "deploy" / "gcp-bootstrap.sh").read_text()
    assert "SECRET_GEMINI_API_KEY_VERSION" in deploy
    assert "atlas-gemini-api-key" in deploy
    assert "GEMINI_API_KEY" in bootstrap
    assert "atlas-gemini-api-key" in bootstrap
    assert "GEMINI_STRATEGY_MODEL=gemini-2.5-pro" in deploy


def test_customer_ui_describes_real_ai_strategy_intelligence():
    s=(ROOT/"app"/"templates"/"customer.html").read_text()
    assert "Strategy Intelligence" in s
    assert "real AI model" in s
    assert "rule-based draft" not in s


def test_strategy_ai_binds_market_context(monkeypatch):
    import app.strategy_ai as sai
    monkeypatch.setattr(sai.settings, "gemini_api_key", "configured")
    monkeypatch.setattr(sai.settings, "groq_api_key", "")
    async def fake(prompt, **kwargs):
        return {
            "version":"atlas-strategy-v1","title":"Wrong Context","summary":"A deliberately mismatched draft used for validation testing.",
            "asset":"forex","symbols":["EUR_USD"],"timeframes":["4h"],"direction":"LONG","strategy_family":"TREND",
            "entry_conditions":[{"type":"trend","rule":"Price above moving average","timeframe":"4h"}],
            "exit_conditions":[{"type":"stop","rule":"Stop at 2 ATR","timeframe":"4h"}],
            "risk_per_trade":0.005,"stop_loss_atr":2,"take_profit_rr":2,"sessions":[],"assumptions":[],"validation_warnings":[],
            "requires_backtest":True,"requires_walk_forward":True,"execution_mode":"PAPER_SHADOW_ONLY","implementation_status":"ATLAS_SUPPORTED_FAMILY"
        }
    monkeypatch.setattr(sai, "_gemini_json", fake)
    out=asyncio.run(sai.generate_strategy_draft(prompt="Build this strategy for BTC",name="Context",asset="crypto",symbol="BTC/USDT:USDT",timeframe="1h"))
    spec=out["strategy"]
    assert spec["asset"]=="crypto"
    assert spec["symbols"]==["BTC/USDT:USDT"]
    assert spec["timeframes"]==["1h"]
    assert spec["validation_warnings"]
