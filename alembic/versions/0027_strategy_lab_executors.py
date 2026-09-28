"""strategy lab candidates and production executor state

Revision ID: 0027_strategy_lab_executors
Revises: 0026_customer_deriv_accounts
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_strategy_lab_executors"
down_revision = "0026_customer_deriv_accounts"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("strategy_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False, server_default="Atlas Candidate"),
        sa.Column("asset", sa.String(20), nullable=False, server_default="crypto"),
        sa.Column("symbol", sa.String(80), nullable=False, server_default="BTC/USDT:USDT"),
        sa.Column("exchange", sa.String(50), nullable=False, server_default="binance"),
        sa.Column("timeframe", sa.String(20), nullable=False, server_default="1h"),
        sa.Column("spec_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("backtest_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("oos_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("live_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_strategy_candidate_customer_status", "strategy_candidates", ["customer_id", "status"])
    op.create_index("ix_strategy_candidate_customer_id", "strategy_candidates", ["customer_id"])
    op.create_table("trade_executors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("trading_account_id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("asset", sa.String(20), nullable=False, server_default="crypto"),
        sa.Column("exchange", sa.String(50), nullable=False, server_default="binance"),
        sa.Column("symbol", sa.String(80), nullable=False),
        sa.Column("timeframe", sa.String(20), nullable=False, server_default="1h"),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("executed_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("target_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="ARMED"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trade_executor_customer_status", "trade_executors", ["customer_id", "status"])
    op.create_index("ix_trade_executor_customer_id", "trade_executors", ["customer_id"])
    op.create_index("ix_trade_executor_trading_account_id", "trade_executors", ["trading_account_id"])
    op.create_index("ix_trade_executor_bot_id", "trade_executors", ["bot_id"])

def downgrade():
    op.drop_index("ix_trade_executor_bot_id", table_name="trade_executors")
    op.drop_index("ix_trade_executor_trading_account_id", table_name="trade_executors")
    op.drop_index("ix_trade_executor_customer_id", table_name="trade_executors")
    op.drop_index("ix_trade_executor_customer_status", table_name="trade_executors")
    op.drop_table("trade_executors")
    op.drop_index("ix_strategy_candidate_customer_id", table_name="strategy_candidates")
    op.drop_index("ix_strategy_candidate_customer_status", table_name="strategy_candidates")
    op.drop_table("strategy_candidates")
