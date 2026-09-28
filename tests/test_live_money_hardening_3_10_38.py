import os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

os.environ.setdefault('ENVIRONMENT','development')
os.environ.setdefault('APP_ENCRYPTION_KEY','')


def test_oos_promotion_gate_rejects_weak_last_fold_and_tail_loss():
    from app.research_validation import oos_promotion_gate
    good={'status':'OK','oos_total_return':0.20,'folds':[{'total_return':0.03},{'total_return':0.02},{'total_return':0.01},{'total_return':0.04},{'total_return':0.02}]}
    assert oos_promotion_gate(good,min_folds=5,min_total_return=0,min_positive_fold_ratio=.5,max_negative_fold_return=-.2,require_last_fold_positive=True)['passed']
    bad={'status':'OK','oos_total_return':0.20,'folds':[{'total_return':0.03},{'total_return':0.02},{'total_return':-0.25},{'total_return':0.04},{'total_return':-0.01}]}
    assert not oos_promotion_gate(bad,min_folds=5,min_total_return=0,min_positive_fold_ratio=.5,max_negative_fold_return=-.2,require_last_fold_positive=True)['passed']


def test_monte_carlo_requires_real_sample():
    from app.research_validation import monte_carlo_bootstrap
    assert monte_carlo_bootstrap([0.01]*10)['status']=='INSUFFICIENT_DATA'
    out=monte_carlo_bootstrap([0.01,-0.005]*20,trials=50)
    assert out['status']=='OK' and out['trials']==50


def test_correlation_group_blocks_concentration():
    from app.correlation_risk import adjusted_group_exposure
    class P:
        symbol='ETH/USDT:USDT'; quantity=1; mark_price=9000
    out=adjusted_group_exposure([P()],proposed_symbol='SOL/USDT:USDT',proposed_notional=5000,cap_usd=10000)
    assert out['group']=='L1_BETA'
    assert not out['allowed']


def test_versioned_encryption_round_trip(monkeypatch):
    from app import crypto
    from app.config import settings
    import base64
    from cryptography.fernet import Fernet
    v1=Fernet.generate_key().decode(); v2=Fernet.generate_key().decode()
    monkeypatch.setattr(settings,'app_encryption_key',v1)
    monkeypatch.setattr(settings,'app_encryption_keys_json',json.dumps({'v1':v1,'v2':v2}))
    monkeypatch.setattr(settings,'app_encryption_active_key_id','v2')
    value=crypto.encrypt_text('secret-value')
    assert value.startswith('enc:v2:')
    assert crypto.decrypt_text(value)=='secret-value'
    old='enc:v1:'+crypto._fernet_for('v1').encrypt(b'legacy').decode()
    assert crypto.decrypt_text(old)=='legacy'
    assert crypto.rotate_ciphertext(old).startswith('enc:v2:')


def test_parameter_plateau_rejects_single_peak():
    from app.research_validation import parameter_plateau_score
    out=parameter_plateau_score({'variants':[{'sharpe':2.0},{'sharpe':0.2},{'sharpe':0.3},{'sharpe':0.1}]})
    assert not out['robust']


def test_release_version_is_3_10_43():
    root=Path(__file__).resolve().parents[1]
    assert 'app_version: str = "3.10.45"' in (root/'app/config.py').read_text()
    assert '__version__ = "3.10.45"' in (root/'app/__init__.py').read_text()


def test_meta_label_predicts_current_unlabeled_bar():
    import numpy as np
    import pandas as pd
    from app.meta_labeling import meta_label_walk_forward
    n=320
    idx=pd.date_range("2025-01-01", periods=n, freq="h")
    close=100+np.cumsum(np.sin(np.arange(n)/7.0)*0.2+0.15)
    df=pd.DataFrame({"open":close,"high":close+0.5,"low":close-0.5,"close":close,"volume":1000},index=idx)
    out=meta_label_walk_forward(df,horizon=3,min_edge_bps=1,folds=5,threshold=.5)
    assert out["status"] in {"OK","INSUFFICIENT_DATA"}
    if out["status"]=="OK":
        assert out["current_prediction_is_oos"] is True
        assert out["prediction_index"] == str(idx[-1])
        assert out["training_last_label_index"] != out["prediction_index"]


def test_oos_gate_enforces_stability_metrics():
    from app.research_validation import oos_promotion_gate
    oos={"status":"OK","oos_total_return":0.20,"sharpe":0.3,"max_drawdown":-0.10,"trades":50,
         "folds":[{"total_return":0.03},{"total_return":0.02},{"total_return":0.01},{"total_return":0.04},{"total_return":0.02}]}
    assert not oos_promotion_gate(oos,min_folds=5,min_total_return=0,min_positive_fold_ratio=.5,max_negative_fold_return=-.2,require_last_fold_positive=True,min_sharpe=.5,max_drawdown=-.25,min_trades=20)["passed"]


def test_ccxt_payout_is_blocked_outside_development(monkeypatch):
    from app.config import settings
    from app.payout import get_payout_provider, PayoutError
    monkeypatch.setattr(settings,"environment","production")
    monkeypatch.setattr(settings,"external_custody_signer_required",False)
    import pytest
    with pytest.raises(PayoutError):
        get_payout_provider("ccxt")


def test_external_security_audit_redacts_nested_secrets(monkeypatch, capsys):
    from app.config import settings
    from app.security_audit import emit_security_audit
    monkeypatch.setattr(settings,"external_security_audit_enabled",True)
    monkeypatch.setattr(settings,"external_security_audit_required",True)
    assert emit_security_audit(event="TEST", actor_id="tester", detail={"ok":1,"api_token":"secret","nested":{"password":"pw","value":"safe"}})
    out=capsys.readouterr().out
    assert '[REDACTED]' in out
    assert 'secret' not in out and 'pw' not in out
    assert 'safe' in out
