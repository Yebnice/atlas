"""billing referrals margin

Revision ID: 0013_billing_referrals_margin
Revises: 0012_customer_trading_isolation
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_billing_referrals_margin"
down_revision = "0012_customer_trading_isolation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("billing_plans",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(80), nullable=False), sa.Column("monthly_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("annual_price", sa.Float(), nullable=False, server_default="0"), sa.Column("ai_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("exchange_connections", sa.Integer(), nullable=False, server_default="0"), sa.Column("active_strategies", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("live_trading", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("paper_trading", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("features_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("code", name="uq_billing_plan_code"))
    op.create_table("subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("customer_id", sa.Integer(), nullable=False), sa.Column("plan_code", sa.String(40), nullable=False),
        sa.Column("billing_interval", sa.String(20), nullable=False, server_default="monthly"), sa.Column("status", sa.String(30), nullable=False, server_default="trialing"),
        sa.Column("provider", sa.String(30), nullable=False, server_default="internal"), sa.Column("provider_customer_id", sa.String(180), nullable=False, server_default=""),
        sa.Column("provider_subscription_id", sa.String(180), nullable=False, server_default=""), sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False), sa.Column("trial_end", sa.DateTime(timezone=True)),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_subscription_id", name="uq_subscription_provider_id"))
    op.create_index("ix_subscription_customer_status", "subscriptions", ["customer_id", "status"])
    op.create_table("referral_codes", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("customer_id", sa.Integer(), nullable=False), sa.Column("code", sa.String(40), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("code", name="uq_referral_code"))
    op.create_index("ix_referral_code_customer", "referral_codes", ["customer_id"])
    op.create_table("referrals", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("referral_code", sa.String(40), nullable=False), sa.Column("referrer_customer_id", sa.Integer(), nullable=False), sa.Column("referred_customer_id", sa.Integer(), nullable=False), sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("qualified_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("referred_customer_id", name="uq_referred_customer"))
    op.create_index("ix_referral_referrer_status", "referrals", ["referrer_customer_id", "status"])
    op.create_table("referral_commissions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("referral_id", sa.Integer(), nullable=False), sa.Column("referral_customer_id", sa.Integer(), nullable=False), sa.Column("referred_customer_id", sa.Integer(), nullable=False), sa.Column("subscription_id", sa.Integer(), nullable=False), sa.Column("gross_revenue", sa.Float(), nullable=False, server_default="0"), sa.Column("commission_pct", sa.Float(), nullable=False, server_default="0"), sa.Column("commission_amount", sa.Float(), nullable=False, server_default="0"), sa.Column("provider_reference", sa.String(180), nullable=False, server_default=""), sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"), sa.Column("eligible_at", sa.DateTime(timezone=True), nullable=False), sa.Column("paid_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("subscription_id", "referral_id", "provider_reference", name="uq_referral_commission_invoice"))
    op.create_index("ix_referral_commission_referrer_status", "referral_commissions", ["referral_customer_id", "status"])
    op.create_table("revenue_ledger", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("customer_id", sa.Integer()), sa.Column("subscription_id", sa.Integer()), sa.Column("provider", sa.String(30), nullable=False, server_default="internal"), sa.Column("provider_reference", sa.String(180), nullable=False), sa.Column("gross_amount", sa.Float(), nullable=False, server_default="0"), sa.Column("refunds", sa.Float(), nullable=False, server_default="0"), sa.Column("net_amount", sa.Float(), nullable=False, server_default="0"), sa.Column("currency", sa.String(10), nullable=False, server_default="USD"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("provider", "provider_reference", name="uq_revenue_provider_reference"))
    op.create_index("ix_revenue_created", "revenue_ledger", ["created_at"])
    op.create_table("cost_ledger", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("customer_id", sa.Integer()), sa.Column("category", sa.String(40), nullable=False), sa.Column("provider", sa.String(60), nullable=False, server_default=""), sa.Column("amount", sa.Float(), nullable=False, server_default="0"), sa.Column("currency", sa.String(10), nullable=False, server_default="USD"), sa.Column("reference", sa.String(180), nullable=False, server_default=""), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_cost_created_category", "cost_ledger", ["created_at", "category"])
    op.create_index("ix_cost_customer", "cost_ledger", ["customer_id"])


def downgrade():
    for t in ["cost_ledger","revenue_ledger","referral_commissions","referrals","referral_codes","subscriptions","billing_plans"]:
        op.drop_table(t)
