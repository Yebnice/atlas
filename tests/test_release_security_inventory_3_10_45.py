from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app" / "main.py"


def _routes():
    tree = ast.parse(MAIN.read_text())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            if not (isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app"):
                continue
            if dec.func.attr not in {"get", "post", "put", "patch", "delete"}:
                continue
            path = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else None
            if not isinstance(path, str):
                continue
            out.append((dec.func.attr.upper(), path, node.name, ast.get_source_segment(MAIN.read_text(), node) or ""))
    return out


def test_customer_mutations_have_explicit_auth_boundary():
    for verb, path, name, body in _routes():
        if not path.startswith("/api/customer/"):
            continue
        # Public/customer login and auth endpoints live outside /api/customer/.
        if verb in {"POST", "PUT", "PATCH", "DELETE"}:
            assert any(token in body for token in ("get_customer(", "customer_claims(")), (verb, path, name)


def test_admin_mutations_have_admin_auth_boundary():
    for verb, path, name, body in _routes():
        if not path.startswith("/api/admin/"):
            continue
        if path.startswith("/api/admin/auth/"):
            continue
        assert "auth(" in body, (verb, path, name)


def test_production_docker_contains_migrations_and_not_test_suite():
    docker = (ROOT / "Dockerfile").read_text()
    assert "COPY alembic ./alembic" in docker
    assert "COPY alembic.ini ./alembic.ini" in docker
    assert "COPY tests" not in docker
    assert "RUN pip install --no-cache-dir -r requirements.txt" in docker
    assert "pytest" not in (ROOT / "requirements.txt").read_text()


def test_api_deploy_uses_read_only_champion_store_and_no_admin_token():
    deploy = (ROOT / "deploy" / "cloud-run-deploy.sh").read_text()
    assert "readonly=true" in deploy
    assert "ADMIN_TOKEN=atlas-admin-token" not in deploy
    assert "SUPABASE_ANON_KEY=atlas-supabase-anon-key" in deploy
    assert "FUNDING_WEBHOOK_SECRET=atlas-funding-webhook-secret" in deploy
    assert "mount-path=/app/model-staging" not in deploy


def test_worker_gets_model_private_key_but_api_does_not():
    api = (ROOT / "deploy" / "cloud-run-deploy.sh").read_text()
    worker = (ROOT / "deploy" / "cloud-run-worker-deploy.sh").read_text()
    assert "MODEL_SIGNING_PRIVATE_KEY=" not in api
    assert "MODEL_SIGNING_PRIVATE_KEY=$SECRET_MODEL_SIGNING_PRIVATE_REF" in worker


def test_tron_runtime_contains_no_master_seed_configuration():
    for path in [ROOT / "app", ROOT / "deploy", ROOT / ".env.example", ROOT / ".env.production.example"]:
        files = path.rglob("*") if path.is_dir() else [path]
        for file in files:
            if not file.is_file() or file.suffix in {".pyc"}:
                continue
            text = file.read_text(errors="ignore")
            assert "USDT_TRON_MASTER_SEED_HEX" not in text, file
            assert "usdt_tron_master_seed_hex" not in text, file


def test_customer_mfa_helper_exists_and_requires_verified_totp():
    main = MAIN.read_text()
    assert "async def _customer_mfa_state" in main
    assert 'factor_type") or "").lower() == "totp"' in main
    assert 'status") or "").lower() == "verified"' in main


def test_no_raw_exception_text_is_returned_in_http_exception_messages():
    source = MAIN.read_text()
    forbidden = [
        'HTTPException(503, f"TRON reconciliation unavailable: {exc}")',
        'HTTPException(400, f"OANDA verification failed: {exc}")',
        'HTTPException(502, f"Execution failed; reconcile before retrying: {e}")',
    ]
    for item in forbidden:
        assert item not in source


def test_production_model_integrity_uses_public_key_and_worker_private_key():
    cfg = (ROOT / "app" / "config.py").read_text()
    registry = (ROOT / "app" / "model_registry.py").read_text()
    assert "MODEL_SIGNING_PUBLIC_KEY" in cfg
    assert "MODEL_SIGNING_PRIVATE_KEY" in cfg
    assert "manifest_signature" in registry
    assert "verify_artifact_signature" in registry


def test_current_release_identity_is_3_10_45():
    assert 'app_version: str = "3.10.45"' in (ROOT / "app" / "config.py").read_text()
    assert '__version__ = "3.10.45"' in (ROOT / "app" / "__init__.py").read_text()
    assert 'versionName = "3.10.45"' in (ROOT / "android" / "app" / "build.gradle.kts").read_text()


def test_bootstrap_grants_api_only_supabase_and_funding_secrets():
    bootstrap = (ROOT / "deploy" / "gcp-bootstrap.sh").read_text()
    assert 'grant_secret_access atlas-supabase-anon-key "$SERVICE_ACCOUNT"' in bootstrap
    assert 'grant_secret_access atlas-funding-webhook-secret "$SERVICE_ACCOUNT"' in bootstrap
    assert 'grant_secret_access atlas-supabase-anon-key "$WORKER_SERVICE_ACCOUNT"' not in bootstrap
    assert 'grant_secret_access atlas-funding-webhook-secret "$WORKER_SERVICE_ACCOUNT"' not in bootstrap


def test_bootstrap_uses_least_privilege_secret_sets():
    bootstrap = (ROOT / "deploy" / "gcp-bootstrap.sh").read_text()
    common = [
        "atlas-database-url", "atlas-secret-key", "atlas-app-encryption-key",
        "atlas-redis-url", "atlas-usdt-tron-account-xpub", "atlas-trongrid-api-key",
        "atlas-gemini-api-key",
    ]
    loop_line = next(line for line in bootstrap.splitlines() if line.startswith("for secret in "))
    for name in common:
        assert name in loop_line
    assert 'grant_secret_access "$secret" "$SERVICE_ACCOUNT"' in bootstrap
    assert 'grant_secret_access "$secret" "$WORKER_SERVICE_ACCOUNT"' in bootstrap
