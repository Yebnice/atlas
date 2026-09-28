from pathlib import Path

def test_version_and_distributed_security_controls():
    cfg = Path("app/config.py").read_text()
    main = Path("app/main.py").read_text()
    req = Path("requirements.txt").read_text()
    assert 'app_version: str = "3.10.45"' in cfg
    assert 'allow_rate_limit' in main
    assert 'check_redis' in main
    assert 'ServiceHeartbeat' in main
    assert 'redis==' in req

def test_withdrawal_risk_engine_and_explicit_review():
    risk = Path("app/withdrawal_risk.py").read_text()
    main = Path("app/main.py").read_text()
    assert 'NEW_DESTINATION' in risk
    assert '24H_VELOCITY_LIMIT' in risk
    assert 'WITHDRAWAL_RISK_REVIEWED' in main
    assert 'risk_reviewed_by' in main
    assert 'explicit risk review before release' in main

def test_recovery_is_status_only_and_no_blind_retry():
    main = Path("app/main.py").read_text()
    assert 'WITHDRAWAL_RECOVERY_DUE' in main
    assert 'no blind payout retry' in main

def test_production_compose_has_redis():
    compose = Path("docker-compose.production.yml").read_text()
    assert 'redis:8-alpine' in compose
    assert 'REDIS_URL: redis://redis:6379/0' in compose
