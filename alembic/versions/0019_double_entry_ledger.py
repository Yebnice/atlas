"""Add immutable balanced double-entry journal tables."""
from alembic import op
import sqlalchemy as sa

revision = "0019_double_entry_ledger"
down_revision = "0018_customer_omnibus_ledger"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "ledger_journals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("currency", sa.String(length=20), nullable=False, server_default="USDT"),
        sa.Column("entry_type", sa.String(length=60), nullable=False),
        sa.Column("reference_type", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("reference_id", sa.String(length=180), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(length=220), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_ledger_journal_idempotency"),
    )
    op.create_index("ix_ledger_journal_reference", "ledger_journals", ["reference_type", "reference_id"])
    op.create_index("ix_ledger_journal_created", "ledger_journals", ["created_at"])
    op.create_table(
        "ledger_journal_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("account_code", sa.String(length=180), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=20), nullable=False, server_default="USDT"),
        sa.Column("debit", sa.Numeric(38, 6), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(38, 6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("journal_id", "line_no", name="uq_ledger_journal_line_no"),
    )
    op.create_index("ix_ledger_journal_line_account", "ledger_journal_lines", ["account_code"])
    op.create_index("ix_ledger_journal_line_customer", "ledger_journal_lines", ["customer_id", "created_at"])

def downgrade():
    op.drop_index("ix_ledger_journal_line_customer", table_name="ledger_journal_lines")
    op.drop_index("ix_ledger_journal_line_account", table_name="ledger_journal_lines")
    op.drop_table("ledger_journal_lines")
    op.drop_index("ix_ledger_journal_created", table_name="ledger_journals")
    op.drop_index("ix_ledger_journal_reference", table_name="ledger_journals")
    op.drop_table("ledger_journals")
