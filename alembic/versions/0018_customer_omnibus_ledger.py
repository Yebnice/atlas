"""Add customer money ledger and cash-only trading reservation state."""
from alembic import op
import sqlalchemy as sa

revision = "0018_customer_omnibus_ledger"
down_revision = "0017_oanda_reconciliation"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "customer_ledger_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=20), nullable=False, server_default="USDT"),
        sa.Column("available", sa.Numeric(38, 6), nullable=False, server_default="0"),
        sa.Column("trading_reserved", sa.Numeric(38, 6), nullable=False, server_default="0"),
        sa.Column("withdrawal_reserved", sa.Numeric(38, 6), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("customer_id", "currency", name="uq_customer_ledger_account_currency"),
    )
    op.create_index("ix_customer_ledger_account_customer", "customer_ledger_accounts", ["customer_id"])
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=20), nullable=False, server_default="USDT"),
        sa.Column("entry_type", sa.String(length=40), nullable=False),
        sa.Column("debit", sa.Numeric(38, 6), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(38, 6), nullable=False, server_default="0"),
        sa.Column("amount", sa.Numeric(38, 6), nullable=False, server_default="0"),
        sa.Column("reference_type", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("reference_id", sa.String(length=180), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_ledger_entry_idempotency"),
    )
    op.create_index("ix_ledger_entry_customer_created", "ledger_entries", ["customer_id", "created_at"])
    op.create_index("ix_ledger_entry_reference", "ledger_entries", ["reference_type", "reference_id"])
    op.add_column("positions", sa.Column("reserved_capital", sa.Float(), nullable=False, server_default="0"))

def downgrade():
    op.drop_column("positions", "reserved_capital")
    op.drop_index("ix_ledger_entry_reference", table_name="ledger_entries")
    op.drop_index("ix_ledger_entry_customer_created", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index("ix_customer_ledger_account_customer", table_name="customer_ledger_accounts")
    op.drop_table("customer_ledger_accounts")
