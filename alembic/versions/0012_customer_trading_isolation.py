"""Add customer-scoped trading accounts, trades and positions."""
from alembic import op
import sqlalchemy as sa

revision = "0012_customer_trading_isolation"
down_revision = "0011_withdrawal_risk_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trading_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=20), nullable=False, server_default="USDT"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="ACTIVE"),
        sa.Column("cash_equity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("equity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("peak_equity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("daily_start_equity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("daily_start_date", sa.Date(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reserved_margin", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("customer_id", name="uq_trading_account_customer"),
    )
    op.create_index("ix_trading_account_customer_id", "trading_accounts", ["customer_id"])
    op.create_index("ix_trading_account_status", "trading_accounts", ["status"])

    op.add_column("trades", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.add_column("trades", sa.Column("trading_account_id", sa.Integer(), nullable=True))
    op.create_index("ix_trades_customer_id", "trades", ["customer_id"])
    op.create_index("ix_trades_trading_account_id", "trades", ["trading_account_id"])

    # Existing positions are legacy/global rows and remain customer_id NULL.
    # Drop the global symbol uniqueness so separate customers can hold the same market.
    with op.batch_alter_table("positions", recreate="auto") as batch:
        batch.add_column(sa.Column("customer_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("trading_account_id", sa.Integer(), nullable=True))
        batch.drop_constraint("uq_position_symbol", type_="unique")
        batch.create_unique_constraint("uq_position_customer_exchange_symbol", ["customer_id", "exchange", "symbol"])
        batch.create_index("ix_positions_customer_id", ["customer_id"])
        batch.create_index("ix_position_customer_status", ["customer_id", "quantity"])


def downgrade():
    with op.batch_alter_table("positions", recreate="auto") as batch:
        batch.drop_index("ix_position_customer_status")
        batch.drop_index("ix_positions_customer_id")
        batch.drop_constraint("uq_position_customer_exchange_symbol", type_="unique")
        batch.drop_column("trading_account_id")
        batch.drop_column("customer_id")
        batch.create_unique_constraint("uq_position_symbol", ["symbol"])
    op.drop_index("ix_trades_trading_account_id", table_name="trades")
    op.drop_index("ix_trades_customer_id", table_name="trades")
    op.drop_column("trades", "trading_account_id")
    op.drop_column("trades", "customer_id")
    op.drop_index("ix_trading_account_status", table_name="trading_accounts")
    op.drop_index("ix_trading_account_customer_id", table_name="trading_accounts")
    op.drop_table("trading_accounts")
