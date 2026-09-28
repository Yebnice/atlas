"""AtlasRisk 3.10.45: custody, auth, deployment and database hardening."""
from alembic import op
import sqlalchemy as sa

revision = "0038_security_custody_database_hardening"
down_revision = "0037_execution_reserve_hardening"
branch_labels = None
depends_on = None

def _has_col(bind, table, column):
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}

def upgrade():
    bind = op.get_bind()
    if not _has_col(bind, "withdrawal_step_up_tokens", "proposal_digest"):
        op.add_column("withdrawal_step_up_tokens", sa.Column("proposal_digest", sa.String(length=64), nullable=False, server_default=""))
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("UPDATE withdrawal_step_up_tokens SET proposal_digest = :legacy WHERE proposal_digest = '' OR proposal_digest IS NULL"), {"legacy": "0" * 64})
        # Customer-owned records: new writes cannot cross-link different customers;
        # existing rows are validated later after orphan cleanup.
        constraints = [
            ("fk_smart_trades_customer", "smart_trades", "customer_id", "customer_profiles(id)"),
            ("fk_smart_trades_account", "smart_trades", "trading_account_id", "trading_accounts(id)"),
            ("fk_dca_bots_customer", "dca_bots", "customer_id", "customer_profiles(id)"),
            ("fk_dca_bots_account", "dca_bots", "trading_account_id", "trading_accounts(id)"),
            ("fk_grid_bots_customer", "grid_bots", "customer_id", "customer_profiles(id)"),
            ("fk_grid_bots_account", "grid_bots", "trading_account_id", "trading_accounts(id)"),
            ("fk_trade_executors_customer", "trade_executors", "customer_id", "customer_profiles(id)"),
            ("fk_trade_executors_account", "trade_executors", "trading_account_id", "trading_accounts(id)"),
            ("fk_strategy_candidates_customer", "strategy_candidates", "customer_id", "customer_profiles(id)"),
            ("fk_strategy_drafts_customer", "strategy_drafts", "customer_id", "customer_profiles(id)"),
            ("fk_customer_binance_customer", "customer_binance_accounts", "customer_id", "customer_profiles(id)"),
            ("fk_customer_deriv_customer", "customer_deriv_accounts", "customer_id", "customer_profiles(id)"),
            ("fk_customer_oanda_customer", "customer_oanda_accounts", "customer_id", "customer_profiles(id)"),
            ("fk_withdrawal_stepup_customer", "withdrawal_step_up_tokens", "auth_user_id", "customer_profiles(auth_user_id)"),
            ("fk_funding_transaction_customer", "funding_transactions", "customer_id", "customer_profiles(id)"),
            ("fk_funding_transaction_wallet", "funding_transactions", "wallet_id", "wallets(id)"),
        ]
        for cname, table, col, ref in constraints:
            if cname not in {c.get("name") for c in sa.inspect(bind).get_foreign_keys(table)}:
                op.execute(sa.text(f'ALTER TABLE "{table}" ADD CONSTRAINT "{cname}" FOREIGN KEY ("{col}") REFERENCES {ref} NOT VALID'))
        for table, expr, cname in [
            ("trades", "reserved_cash >= 0", "ck_trades_reserved_cash_nonnegative"),
            ("withdrawal_step_up_tokens", "proposal_digest <> ''", "ck_stepup_proposal_digest_nonempty"),
        ]:
            if cname not in {c.get("name") for c in sa.inspect(bind).get_check_constraints(table)}:
                op.create_check_constraint(cname, table, expr)

def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for cname, table in [
            ("ck_stepup_proposal_digest_nonempty", "withdrawal_step_up_tokens"),
            ("ck_trades_reserved_cash_nonnegative", "trades"),
        ]:
            op.drop_constraint(cname, table_name=table, type_="check")
        for cname in [
            "fk_funding_transaction_wallet","fk_funding_transaction_customer","fk_withdrawal_stepup_customer",
            "fk_customer_oanda_customer","fk_customer_deriv_customer","fk_customer_binance_customer",
            "fk_strategy_drafts_customer","fk_strategy_candidates_customer","fk_trade_executors_account",
            "fk_trade_executors_customer","fk_grid_bots_account","fk_grid_bots_customer",
            "fk_dca_bots_account","fk_dca_bots_customer","fk_smart_trades_account","fk_smart_trades_customer",
        ]:
            # table lookup is intentionally defensive for partial rollbacks.
            for table in ["funding_transactions","withdrawal_step_up_tokens","customer_oanda_accounts","customer_deriv_accounts","customer_binance_accounts","strategy_drafts","strategy_candidates","trade_executors","grid_bots","dca_bots","smart_trades"]:
                op.execute(sa.text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{cname}"'))
    if _has_col(bind, "withdrawal_step_up_tokens", "proposal_digest"):
        op.drop_column("withdrawal_step_up_tokens", "proposal_digest")
