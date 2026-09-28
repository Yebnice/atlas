"""customer OANDA credentials and isolation

Revision ID: 0025_customer_oanda_accounts
Revises: 0024_adaptive_bot_controller
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_customer_oanda_accounts"
down_revision = "0024_adaptive_bot_controller"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_oanda_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.String(length=80), nullable=False),
        sa.Column("api_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("practice", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_trade", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_id", name="uq_customer_oanda_account_customer"),
        sa.UniqueConstraint("account_id", name="uq_customer_oanda_account_account_id"),
    )
    op.create_index("ix_customer_oanda_account_customer_id", "customer_oanda_accounts", ["customer_id"])
    op.create_index("ix_customer_oanda_account_status", "customer_oanda_accounts", ["status"])


def downgrade():
    op.drop_index("ix_customer_oanda_account_status", table_name="customer_oanda_accounts")
    op.drop_index("ix_customer_oanda_account_customer_id", table_name="customer_oanda_accounts")
    op.drop_table("customer_oanda_accounts")
