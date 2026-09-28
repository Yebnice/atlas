"""Add durable OANDA reconciliation cursor."""
from alembic import op
import sqlalchemy as sa

revision = "0017_oanda_reconciliation"
down_revision = "0016_arbitrage_research"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "oanda_reconciliation_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.String(length=80), nullable=False),
        sa.Column("last_transaction_id", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("environment", sa.String(length=20), nullable=False, server_default="practice"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="READY"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("account_id", name="uq_oanda_reconciliation_account"),
    )

def downgrade():
    op.drop_table("oanda_reconciliation_state")
