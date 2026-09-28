"""Link customer withdrawal requests to customer wallets.
Revision ID: 0007_customer_withdrawal_wallet_links
Revises: 0006_real_usdt_tron_deposits
"""
from alembic import op
import sqlalchemy as sa
revision = "0007_customer_withdrawal_wallet_links"
down_revision = "0006_real_usdt_tron_deposits"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("withdrawals", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.add_column("withdrawals", sa.Column("wallet_id", sa.Integer(), nullable=True))
    op.create_index("ix_withdrawal_customer_id", "withdrawals", ["customer_id"])
    op.create_index("ix_withdrawal_wallet_id", "withdrawals", ["wallet_id"])

def downgrade():
    op.drop_index("ix_withdrawal_wallet_id", table_name="withdrawals")
    op.drop_index("ix_withdrawal_customer_id", table_name="withdrawals")
    op.drop_column("withdrawals", "wallet_id")
    op.drop_column("withdrawals", "customer_id")
