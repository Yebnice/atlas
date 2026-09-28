"""financial precision, TRON recovery metadata, and SQLite/live safety
Revision ID: 0030_financial_precision_and_wallet_recovery
Revises: 0029_executor_live_approval
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_financial_precision_and_wallet_recovery"
down_revision = "0029_executor_live_approval"
branch_labels = None
depends_on = None

FINANCIAL = {
    "app_state": ["cash_equity", "equity", "peak_equity", "daily_start_equity", "realized_pnl", "unrealized_pnl"],
    "trading_accounts": ["cash_equity", "equity", "peak_equity", "daily_start_equity", "realized_pnl", "unrealized_pnl", "reserved_margin"],
    "trades": ["quantity", "requested_quantity", "filled_quantity", "remaining_quantity", "requested_price", "average_fill_price", "fee", "notional", "stop_loss_price", "take_profit_price"],
    "positions": ["quantity", "average_entry_price", "mark_price", "realized_pnl", "unrealized_pnl", "reserved_capital"],
    "withdrawals": ["amount"],
    "wallets": ["available_balance", "locked_balance"],
    "referral_commissions": ["gross_revenue", "commission_amount"],
    "revenue_ledger": ["gross_amount", "refunds", "net_amount"],
    "cost_ledger": ["amount"],
    "smart_trades": ["entry_price", "quantity", "stop_loss_price", "take_profit_1", "take_profit_2", "take_profit_3"],
    "dca_bots": ["initial_quote", "safety_order_quote"],
    "grid_bots": ["lower_price", "upper_price", "quote_per_grid"],
    "trade_executors": ["executed_quantity", "target_quantity"],
    "funding_transactions": ["amount"],
    "billing_plans": ["monthly_price", "annual_price"],
    "arbitrage_opportunities": ["start_quote", "end_quote"],
}


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        # SQLite has no native ALTER COLUMN TYPE; Alembic batch mode recreates the table safely.
        for table, cols in FINANCIAL.items():
            with op.batch_alter_table(table, recreate="auto") as batch:
                for col in cols:
                    batch.alter_column(col, existing_type=sa.Float(), type_=sa.Numeric(38, 18, asdecimal=False))
    else:
        for table, cols in FINANCIAL.items():
            for col in cols:
                kwargs = {}
                if dialect == "postgresql":
                    kwargs["postgresql_using"] = f'"{col}"::numeric(38,18)'
                op.alter_column(table, col, existing_type=sa.Float(), type_=sa.Numeric(38, 18, asdecimal=False), **kwargs)

    op.add_column("wallets", sa.Column("derivation_path", sa.String(length=100), nullable=False, server_default=""))
    op.add_index("ix_wallets_derivation_path", "wallets", ["derivation_path"])

    # Existing Atlas TRON addresses used the legacy customer-account path. Preserve those addresses,
    # record the exact legacy path, and use standard BIP44 address-index derivation for new wallets.
    op.execute(sa.text("""
        UPDATE wallets
           SET derivation_path = :prefix || CAST(customer_id AS TEXT) || :suffix
         WHERE currency = 'USDT' AND network = 'TRON' AND derivation_path = ''
    """).bindparams(prefix="m/44'/195'/", suffix="'/0/0"))


def downgrade():
    op.drop_index("ix_wallets_derivation_path", table_name="wallets")
    op.drop_column("wallets", "derivation_path")
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        for table, cols in FINANCIAL.items():
            with op.batch_alter_table(table, recreate="auto") as batch:
                for col in cols:
                    batch.alter_column(col, existing_type=sa.Numeric(38, 18, asdecimal=False), type_=sa.Float())
    else:
        for table, cols in FINANCIAL.items():
            for col in cols:
                op.alter_column(table, col, existing_type=sa.Numeric(38, 18, asdecimal=False), type_=sa.Float())
