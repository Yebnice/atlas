"""trading product features

Revision ID: 0014_trading_product_features
Revises: 0013_billing_referrals_margin
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_trading_product_features"
down_revision = "0013_billing_referrals_margin"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("smart_trades",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("customer_id", sa.Integer(), nullable=False), sa.Column("trading_account_id", sa.Integer(), nullable=False),
        sa.Column("exchange", sa.String(50), nullable=False, server_default=""), sa.Column("symbol", sa.String(80), nullable=False), sa.Column("side", sa.String(10), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False, server_default="0"), sa.Column("quantity", sa.Float(), nullable=False, server_default="0"), sa.Column("stop_loss_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("take_profit_1", sa.Float(), nullable=False, server_default="0"), sa.Column("take_profit_2", sa.Float(), nullable=False, server_default="0"), sa.Column("take_profit_3", sa.Float(), nullable=False, server_default="0"),
        sa.Column("trailing_stop_pct", sa.Float(), nullable=False, server_default="0"), sa.Column("breakeven_at_r", sa.Float(), nullable=False, server_default="0"), sa.Column("status", sa.String(30), nullable=False, server_default="PAPER"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_smart_trade_customer_status", "smart_trades", ["customer_id", "status"])
    op.create_index("ix_smart_trades_customer", "smart_trades", ["customer_id"])

    op.create_table("dca_bots",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("customer_id", sa.Integer(), nullable=False), sa.Column("trading_account_id", sa.Integer(), nullable=False),
        sa.Column("exchange", sa.String(50), nullable=False, server_default=""), sa.Column("symbol", sa.String(80), nullable=False), sa.Column("side", sa.String(10), nullable=False, server_default="LONG"),
        sa.Column("initial_quote", sa.Float(), nullable=False, server_default="0"), sa.Column("safety_order_quote", sa.Float(), nullable=False, server_default="0"), sa.Column("max_safety_orders", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("deviation_pct", sa.Float(), nullable=False, server_default="1"), sa.Column("volume_scale", sa.Float(), nullable=False, server_default="1.5"), sa.Column("step_scale", sa.Float(), nullable=False, server_default="1.25"),
        sa.Column("take_profit_pct", sa.Float(), nullable=False, server_default="2"), sa.Column("stop_loss_pct", sa.Float(), nullable=False, server_default="5"), sa.Column("trailing_take_profit_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="STOPPED"), sa.Column("mode", sa.String(20), nullable=False, server_default="PAPER"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_dca_bot_customer_status", "dca_bots", ["customer_id", "status"])
    op.create_index("ix_dca_bots_customer", "dca_bots", ["customer_id"])

    op.create_table("customer_alerts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("customer_id", sa.Integer(), nullable=False), sa.Column("alert_type", sa.String(40), nullable=False, server_default="PRICE"),
        sa.Column("symbol", sa.String(80), nullable=False, server_default=""), sa.Column("threshold", sa.Float(), nullable=False, server_default="0"), sa.Column("condition", sa.String(20), nullable=False, server_default="ABOVE"),
        sa.Column("channel", sa.String(20), nullable=False, server_default="IN_APP"), sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"), sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("triggered_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_customer_alert_customer_status", "customer_alerts", ["customer_id", "status"])
    op.create_index("ix_customer_alerts_customer", "customer_alerts", ["customer_id"])

    op.create_table("strategy_drafts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("customer_id", sa.Integer(), nullable=False), sa.Column("name", sa.String(120), nullable=False, server_default="Atlas AI Strategy"),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""), sa.Column("strategy_json", sa.Text(), nullable=False, server_default="{}"), sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_strategy_draft_customer_created", "strategy_drafts", ["customer_id", "created_at"])
    op.create_index("ix_strategy_draft_customer", "strategy_drafts", ["customer_id"])


def downgrade():
    for t in ["strategy_drafts", "customer_alerts", "dca_bots", "smart_trades"]:
        op.drop_table(t)
