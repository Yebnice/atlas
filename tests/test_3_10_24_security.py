import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_security_fixed_dependencies():
    req=(ROOT/"requirements.txt").read_text()
    assert "PyJWT==2.15.0" in req
    assert "python-multipart==0.0.32" in req
    assert "cryptography==50.0.1" in req

def test_binance_withdrawals_are_disabled_by_contract():
    src=(ROOT/"app/binance_subaccounts.py").read_text()
    assert 'enableWithdrawals": False' in src
    assert 'enable_withdrawals' in src
    assert 'must have withdrawals disabled' in src

def test_customer_broker_rejects_withdrawal_enabled():
    src=(ROOT/"app/customer_binance_execution.py").read_text()
    assert 'enable_withdrawals' in src
    assert 'has withdrawals enabled' in src

def test_funding_state_transition_is_supported():
    src=(ROOT/"app/main.py").read_text()
    assert 'Invalid funding state transition' in src
    assert 'PENDING": {"CONFIRMED", "FAILED"}' in src

def test_stripe_event_inbox_and_ordering_protection():
    db=(ROOT/"app/db.py").read_text(); main=(ROOT/"app/main.py").read_text()
    assert 'class StripeWebhookEvent' in db
    assert 'uq_stripe_webhook_event_id' in db
    assert 'stripe_last_event_at' in db
    assert "status = 'STALE'" in main

def test_broker_cache_does_not_use_prefix_only():
    src=(ROOT/"app/broker.py").read_text()
    assert 'sha256(config.api_key.encode' in src
    assert 'config.api_key[:8]' not in src

def test_cloud_run_pins_secret_versions_and_uses_lb_ingress():
    src=(ROOT/"deploy/cloud-run-deploy.sh").read_text()
    assert '--ingress internal-and-cloud-load-balancing' in src
    assert ':latest' not in src

def test_android_webview_has_domain_allowlist():
    src=(ROOT/"android/app/src/main/java/com/atlas/trading/MainActivity.kt").read_text()
    assert 'trusted_web_host' in src
    assert 'checkout.stripe.com' in (ROOT/"android/app/src/main/res/values/strings.xml").read_text()

def test_customer_ui_no_direct_api_value_innerhtml():
    src=(ROOT/"app/templates/customer.html").read_text()
    for line in src.splitlines():
        if 'innerHTML' in line and 'function esc' not in line:
            assert 'data:image' not in line or 'qr_code' not in line
            assert '${' not in line


def test_admin_security_helpers_exist_and_are_referenced():
    import ast
    src=(ROOT/"app/main.py").read_text(); tree=ast.parse(src)
    defs={n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    assert {"auth","admin_claims","approver_auth","customer_claims"}.issubset(defs)
    assert "await auth(x_admin_token, authorization)" in src
    assert "approver_auth(req.admin_id, x_approver_token, x_admin_token)" in src



def test_customer_access_token_is_session_scoped():
    src=(ROOT/"app/templates/customer.html").read_text()
    token_section=src[src.index("const tokenKey"):src.index("// Atlas UI layer")]
    assert "sessionStorage.getItem(tokenKey)" in token_section
    assert "sessionStorage.setItem(tokenKey" in token_section
    assert "localStorage.setItem(tokenKey" not in token_section
    assert "localStorage.getItem(tokenKey)" not in token_section
