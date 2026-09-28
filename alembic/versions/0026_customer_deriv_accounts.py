"""customer Deriv live trading credentials

Revision ID: 0026_customer_deriv_accounts
Revises: 0025_customer_oanda_accounts
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_customer_deriv_accounts"
down_revision = "0025_customer_oanda_accounts"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "customer_deriv_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.String(length=80), nullable=False),
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("api_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("can_trade", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_id", name="uq_customer_deriv_account_customer"),
        sa.UniqueConstraint("account_id", name="uq_customer_deriv_account_account_id"),
    )
    op.create_index("ix_customer_deriv_account_customer_id", "customer_deriv_accounts", ["customer_id"])
    op.create_index("ix_customer_deriv_account_status", "customer_deriv_accounts", ["status"])

def downgrade():
    op.drop_index("ix_customer_deriv_account_status", table_name="customer_deriv_accounts")
    op.drop_index("ix_customer_deriv_account_customer_id", table_name="customer_deriv_accounts")
    op.drop_table("customer_deriv_accounts")
