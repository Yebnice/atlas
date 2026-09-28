"""Real USDT TRC-20 deposit addresses and on-chain metadata.
Revision ID: 0006_real_usdt_tron_deposits
Revises: 0005_customers_wallets_funding
"""
from alembic import op
import sqlalchemy as sa
revision = "0006_real_usdt_tron_deposits"
down_revision = "0005_customers_wallets_funding"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("wallets", sa.Column("network", sa.String(40), nullable=False, server_default=""))
    op.add_column("wallets", sa.Column("deposit_address", sa.String(128), nullable=False, server_default=""))
    op.add_column("wallets", sa.Column("token_contract", sa.String(128), nullable=False, server_default=""))
    op.create_index("ix_wallets_deposit_address", "wallets", ["deposit_address"])

def downgrade():
    op.drop_index("ix_wallets_deposit_address", table_name="wallets")
    op.drop_column("wallets", "token_contract")
    op.drop_column("wallets", "deposit_address")
    op.drop_column("wallets", "network")
