from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_schema_repair_migration_exists_after_0040():
    src = (ROOT / "alembic/versions/0041_runtime_schema_repairs.py").read_text()
    assert 'revision = "0041_runtime_schema_repairs"' in src
    assert 'down_revision = "0040_database_integrity_and_ledger_immutability"' in src
    for token in ("proposal_digest", "execution_operator", "execution_started_at", "reconciled_at", "consecutive_errors"):
        assert token in src
    assert 'customer_binance_accounts' in src
    assert 'atlas_ledger_journal_deferred_check' in src
