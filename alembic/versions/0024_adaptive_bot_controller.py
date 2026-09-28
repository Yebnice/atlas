"""Persistent adaptive AI bot controller."""
from alembic import op
import sqlalchemy as sa

revision = "0024_adaptive_bot_controller"
down_revision = "0023_security_billing_hardening"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "adaptive_trading_bots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("trading_account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False, server_default="Atlas Adaptive AI"),
        sa.Column("asset", sa.String(length=20), nullable=False, server_default="crypto"),
        sa.Column("symbol", sa.String(length=80), nullable=False, server_default="BTC/USDT:USDT"),
        sa.Column("exchange", sa.String(length=50), nullable=False, server_default="binance"),
        sa.Column("timeframe", sa.String(length=20), nullable=False, server_default="1h"),
        sa.Column("days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("risk_fraction", sa.Float(), nullable=False, server_default="0.005"),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="STOPPED"),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="PAPER"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_decision", sa.String(length=30), nullable=False, server_default="NONE"),
        sa.Column("last_stage", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("last_model_version", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("consecutive_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_id", "name", name="uq_adaptive_bot_customer_name"),
    )
    op.create_index("ix_adaptive_bot_customer_status", "adaptive_trading_bots", ["customer_id", "status"])
    op.create_index("ix_adaptive_bot_account", "adaptive_trading_bots", ["trading_account_id"])

def downgrade():
    op.drop_index("ix_adaptive_bot_account", table_name="adaptive_trading_bots")
    op.drop_index("ix_adaptive_bot_customer_status", table_name="adaptive_trading_bots")
    op.drop_table("adaptive_trading_bots")
