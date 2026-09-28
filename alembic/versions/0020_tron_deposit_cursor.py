"""Add durable per-wallet TRON deposit scan cursors."""
from alembic import op
import sqlalchemy as sa

revision = "0020_tron_deposit_cursor"
down_revision = "0019_double_entry_ledger"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "tron_deposit_cursors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("last_block_timestamp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("wallet_id", name="uq_tron_deposit_cursor_wallet"),
    )
    op.create_index("ix_tron_deposit_cursor_wallet", "tron_deposit_cursors", ["wallet_id"])

def downgrade():
    op.drop_index("ix_tron_deposit_cursor_wallet", table_name="tron_deposit_cursors")
    op.drop_table("tron_deposit_cursors")
