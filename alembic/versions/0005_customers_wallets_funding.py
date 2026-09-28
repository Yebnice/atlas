"""Customer accounts, trading wallets and funding ledger.
Revision ID: 0005_customers_wallets_funding
Revises: 0004_safety_hardening
"""
from alembic import op
import sqlalchemy as sa
revision = "0005_customers_wallets_funding"
down_revision = "0004_safety_hardening"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "customer_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("auth_user_id", sa.String(120), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("auth_user_id", name="uq_customer_auth_user_id"),
    )
    op.create_table(
        "wallets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(20), nullable=False),
        sa.Column("wallet_type", sa.String(40), nullable=False, server_default="INTERNAL_TRADING"),
        sa.Column("available_balance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("locked_balance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_id", "currency", name="uq_wallet_customer_currency"),
    )
    op.create_index("ix_wallets_customer_id", "wallets", ["customer_id"])
    op.create_table(
        "funding_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False, server_default=""),
        sa.Column("provider_reference", sa.String(180), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(20), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "provider_reference", name="uq_funding_provider_reference"),
    )
    op.create_index("ix_funding_customer_status", "funding_transactions", ["customer_id", "status"])

def downgrade():
    op.drop_index("ix_funding_customer_status", table_name="funding_transactions")
    op.drop_table("funding_transactions")
    op.drop_index("ix_wallets_customer_id", table_name="wallets")
    op.drop_table("wallets")
    op.drop_table("customer_profiles")
