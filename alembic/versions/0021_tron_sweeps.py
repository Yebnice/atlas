"""Add controlled TRON sweep intents."""
from alembic import op
import sqlalchemy as sa

revision = "0021_tron_sweeps"
down_revision = "0020_tron_deposit_cursor"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tron_sweeps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("source_address", sa.Text(), nullable=False),
        sa.Column("treasury_address", sa.Text(), nullable=False),
        sa.Column("amount_raw", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=20), nullable=False, server_default="USDT"),
        sa.Column("contract_address", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="READY_FOR_SIGNER"),
        sa.Column("transaction_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_tron_sweep_idempotency"),
    )
    op.create_index("ix_tron_sweep_wallet_id", "tron_sweeps", ["wallet_id"])
    op.create_index("ix_tron_sweep_wallet_status", "tron_sweeps", ["wallet_id", "status"])


def downgrade():
    op.drop_index("ix_tron_sweep_wallet_status", table_name="tron_sweeps")
    op.drop_index("ix_tron_sweep_wallet_id", table_name="tron_sweeps")
    op.drop_table("tron_sweeps")
