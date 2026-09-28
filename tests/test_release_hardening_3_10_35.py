from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_production_legacy_admin_token_is_not_an_auth_path():
    s=(ROOT/"app/main.py").read_text()
    assert 'if str(settings.environment).lower() != "development":' in s
    assert 'Administrator authentication requires Supabase Auth with MFA outside development' in s

def test_production_migration_gate_exists():
    s=(ROOT/"app/main.py").read_text()
    assert '_assert_database_migrations_current' in s
    assert "alembic upgrade head" in s

def test_security_headers_use_actual_environment():
    s=(ROOT/"app/monitoring.py").read_text()
    assert 'str(settings.environment).lower() == "production"' in s

def test_referral_ui_handlers_exist():
    s=(ROOT/"app/templates/customer.html").read_text()
    assert 'async function createReferralCode()' in s
    assert 'async function claimReferral()' in s

def test_market_controls_are_functional():
    s=(ROOT/"app/templates/customer.html").read_text()
    assert 'data-market-filter="bullish"' in s
    assert "globalSearch')?.addEventListener('input',applyMarketFilters)" in s

def test_current_release_identity_is_3_10_43():
    assert 'app_version: str = "3.10.45"' in (ROOT/"app/config.py").read_text()
    assert '__version__ = "3.10.45"' in (ROOT/"app/__init__.py").read_text()
    assert 'versionName = "3.10.45"' in (ROOT/"android/app/build.gradle.kts").read_text()
