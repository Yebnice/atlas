"""add customer Binance sub-account mappings

Revision ID: 0022_binance_customer_subaccounts
Revises: 0021_tron_sweeps
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_binance_customer_subaccounts"
down_revision = "0021_tron_sweeps"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_binance_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("subaccount_id", sa.String(length=120), nullable=False),
        sa.Column("api_key", sa.String(length=180), nullable=False, server_default=""),
        sa.Column("secret_ref", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("market_type", sa.String(length=30), nullable=False, server_default="spot"),
        sa.Column("can_trade", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("margin_trade", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("futures_trade", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("universal_transfer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_id", name="uq_customer_binance_account_customer"),
        sa.UniqueConstraint("subaccount_id", name="uq_customer_binance_account_subaccount"),
    )
    op.create_index("ix_customer_binance_account_status", "customer_binance_accounts", ["status"])


def downgrade():
    op.drop_index("ix_customer_binance_account_status", table_name="customer_binance_accounts")
    op.drop_table("customer_binance_accounts")
