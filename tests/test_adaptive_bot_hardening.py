from pathlib import Path


def test_adaptive_controller_has_final_runtime_gate_and_live_mode():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "_adaptive_bot_runtime_gate" in source
    assert 'mode="LIVE" if not paper_mode else "PAPER"' in source
    assert "Automation entitlement is no longer active" in source


def test_adaptive_model_training_is_serialized():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "_ensure_adaptive_model_locked" in source
    assert 'lock_key = "adaptive-model:"' in source
    assert "await release_lock(lock_key)" in source


def test_distributed_lock_uses_owner_token_for_release():
    source = Path("app/distributed.py").read_text(encoding="utf-8")
    assert "secrets.token_urlsafe" in source
    assert "ContextVar" in source
    assert "_lock_tokens" in source
    assert "redis.call('get', KEYS[1]) == ARGV[1]" in source


def test_adaptive_bot_stops_after_repeated_controller_errors():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "consecutive_errors = int(row.consecutive_errors or 0) + 1" in source
    assert "if row.consecutive_errors >= 3" in source
    assert 'row.status = "STOPPED"' in source
