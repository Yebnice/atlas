from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_autonomous_cycle_uses_persisted_risk_fraction():
    src = (ROOT / 'app' / 'main.py').read_text()
    start = src.index('async def _run_persisted_adaptive_bot_cycle')
    end = src.index('async def _daily_research_loop')
    chunk = src[start:end]
    assert 'risk_fraction = float(bot.risk_fraction or settings.risk_per_trade)' in chunk
    assert 'risk_cash = equity * float(risk_fraction or settings.risk_per_trade)' in chunk

def test_start_path_schedules_next_cycle_after_initial_run():
    src = (ROOT / 'app' / 'main.py').read_text()
    start = src.index('@app.post("/api/customer/bot/start")')
    end = src.index('@app.', start + 10)
    chunk = src[start:end]
    assert 'existing_bot.next_run_at = datetime.now(timezone.utc)' in chunk
    assert 'row.next_run_at = now2 + __import__("datetime").timedelta' in chunk

def test_challenger_cannot_materially_degrade_incumbent():
    src = (ROOT / 'app' / 'adaptive_bot.py').read_text()
    assert 'max_champion_sharpe_drop' in src
    assert 'max_champion_drawdown_worsening' in src
    assert 'max_champion_return_drop' in src
    assert 'WORSE_THAN_CHAMPION' in src
