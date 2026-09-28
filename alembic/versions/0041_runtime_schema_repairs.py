"""Repair runtime schema columns and the deferred ledger trigger on existing databases."""
from alembic import op
import sqlalchemy as sa

revision = "0041_runtime_schema_repairs"
down_revision = "0040_database_integrity_and_ledger_immutability"
branch_labels = None
depends_on = None


def _has_col(bind, table: str, column: str) -> bool:
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    additions = {
        "withdrawals": [
            sa.Column("proposal_digest", sa.String(64), nullable=False, server_default=""),
            sa.Column("execution_operator", sa.String(120), nullable=False, server_default=""),
            sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        ],
        "oanda_reconciliation_state": [
            sa.Column("consecutive_errors", sa.Integer(), nullable=False, server_default="0"),
        ],
    }
    for table, columns in additions.items():
        existing = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)

    # Fernet ciphertext can exceed the legacy VARCHAR(180) boundary. Alter only
    # when the existing database still has that bounded column.
    if _has_col(bind, "customer_binance_accounts", "api_key"):
        api_key = next(c for c in sa.inspect(bind).get_columns("customer_binance_accounts") if c["name"] == "api_key")
        if isinstance(api_key["type"], sa.String) and getattr(api_key["type"], "length", None) == 180:
            with op.batch_alter_table("customer_binance_accounts") as batch:
                batch.alter_column("api_key", existing_type=sa.String(180), type_=sa.Text(), existing_nullable=False)

    if bind.dialect.name == "postgresql":
        # Repair the deferred validation function/trigger on databases that reached
        # 0040 with an incomplete or missing trigger definition.
        op.execute(sa.text("""
            CREATE OR REPLACE FUNCTION atlas_ledger_journal_deferred_check()
            RETURNS trigger AS $$
            BEGIN
                IF TG_TABLE_NAME = 'ledger_journals' THEN
                    PERFORM atlas_validate_ledger_journal(NEW.id);
                ELSE
                    PERFORM atlas_validate_ledger_journal(COALESCE(NEW.journal_id, OLD.journal_id));
                END IF;
                RETURN COALESCE(NEW, OLD);
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_ledger_journal_deferred_check ON ledger_journals;
            CREATE CONSTRAINT TRIGGER trg_ledger_journal_deferred_check
            AFTER INSERT OR UPDATE OR DELETE ON ledger_journals
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION atlas_ledger_journal_deferred_check();

            DROP TRIGGER IF EXISTS trg_ledger_line_deferred_check ON ledger_journal_lines;
            CREATE CONSTRAINT TRIGGER trg_ledger_line_deferred_check
            AFTER INSERT OR UPDATE OR DELETE ON ledger_journal_lines
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION atlas_ledger_journal_deferred_check();
        """))


def downgrade():
    bind = op.get_bind()
    for table, columns in {
        "withdrawals": ["reconciled_at", "execution_started_at", "execution_operator", "proposal_digest"],
        "oanda_reconciliation_state": ["consecutive_errors"],
    }.items():
        for column in columns:
            if _has_col(bind, table, column):
                op.drop_column(table, column)

    # Leave 0040's ledger triggers in place; this migration repairs them for
    # forward compatibility but does not own the base integrity policy.
