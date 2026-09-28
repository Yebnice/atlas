"""AtlasRisk 3.10.45: bind OTP intents and customer/account ownership at DB level."""
from alembic import op
import sqlalchemy as sa

revision = "0039_otp_and_customer_ownership_hardening"
down_revision = "0038_security_custody_database_hardening"
branch_labels = None
depends_on = None

def _table_exists(bind, table):
    return table in sa.inspect(bind).get_table_names()

def _has_unique(bind, table, name):
    return name in {c.get("name") for c in sa.inspect(bind).get_unique_constraints(table)}

def _has_fk(bind, table, name):
    return name in {c.get("name") for c in sa.inspect(bind).get_foreign_keys(table)}

def upgrade():
    bind = op.get_bind()
    if not _table_exists(bind, "withdrawal_otp_intents"):
        op.create_table(
            "withdrawal_otp_intents",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("jti", sa.String(64), nullable=False),
            sa.Column("auth_user_id", sa.String(120), nullable=False),
            sa.Column("purpose", sa.String(40), nullable=False),
            sa.Column("contact_hash", sa.String(64), nullable=False),
            sa.Column("destination_fingerprint", sa.String(64), nullable=False, server_default=""),
            sa.Column("proposal_digest", sa.String(64), nullable=False, server_default=""),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("jti", name="uq_withdrawal_otp_intent_jti"),
            sa.Index("ix_withdrawal_otp_intent_user_expiry", "auth_user_id", "expires_at"),
        )
    # Composite uniqueness is the target needed for ownership FKs. Existing PKs already make
    # these pairs unique, so the constraint is metadata only and has no duplicate-row risk.
    unique_targets = [
        ("trading_accounts", "uq_trading_account_id_customer", ["id", "customer_id"]),
        ("wallets", "uq_wallet_id_customer", ["id", "customer_id"]),
        ("trades", "uq_trade_id_customer", ["id", "customer_id"]),
    ]
    for table, name, cols in unique_targets:
        if not _has_unique(bind, table, name):
            op.create_unique_constraint(name, table, cols)
    fks = [
        ("trades", "fk_trade_account_customer", ["trading_account_id", "customer_id"], "trading_accounts", ["id", "customer_id"]),
        ("order_commands", "fk_order_command_trade_customer", ["trade_id", "customer_id"], "trades", ["id", "customer_id"]),
        ("positions", "fk_position_account_customer", ["trading_account_id", "customer_id"], "trading_accounts", ["id", "customer_id"]),
        ("positions", "fk_position_trade_customer", ["entry_trade_id", "customer_id"], "trades", ["id", "customer_id"]),
        ("smart_trades", "fk_smart_trade_account_customer", ["trading_account_id", "customer_id"], "trading_accounts", ["id", "customer_id"]),
        ("dca_bots", "fk_dca_bot_account_customer", ["trading_account_id", "customer_id"], "trading_accounts", ["id", "customer_id"]),
        ("grid_bots", "fk_grid_bot_account_customer", ["trading_account_id", "customer_id"], "trading_accounts", ["id", "customer_id"]),
        ("adaptive_trading_bots", "fk_adaptive_bot_account_customer", ["trading_account_id", "customer_id"], "trading_accounts", ["id", "customer_id"]),
        ("trade_executors", "fk_executor_account_customer", ["trading_account_id", "customer_id"], "trading_accounts", ["id", "customer_id"]),
        ("withdrawals", "fk_withdrawal_wallet_customer", ["wallet_id", "customer_id"], "wallets", ["id", "customer_id"]),
        ("funding_transactions", "fk_funding_wallet_customer", ["wallet_id", "customer_id"], "wallets", ["id", "customer_id"]),
    ]
    for table, name, local_cols, ref_table, ref_cols in fks:
        if not _table_exists(bind, table) or not _table_exists(bind, ref_table):
            continue
        if not _has_fk(bind, table, name):
            if bind.dialect.name == "postgresql":
                op.create_foreign_key(name, table, ref_table, local_cols, ref_cols, initially=None, deferrable=False, use_alter=True, postgresql_not_valid=True)
            else:
                # SQLite test databases do not support ALTER TABLE ADD CONSTRAINT; metadata carries
                # the relationship and PostgreSQL enforces it in staging/production.
                pass

def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table, name in [
            ("funding_transactions", "fk_funding_wallet_customer"), ("withdrawals", "fk_withdrawal_wallet_customer"),
            ("trade_executors", "fk_executor_account_customer"), ("adaptive_trading_bots", "fk_adaptive_bot_account_customer"),
            ("grid_bots", "fk_grid_bot_account_customer"), ("dca_bots", "fk_dca_bot_account_customer"),
            ("smart_trades", "fk_smart_trade_account_customer"), ("positions", "fk_position_trade_customer"),
            ("positions", "fk_position_account_customer"), ("order_commands", "fk_order_command_trade_customer"),
            ("trades", "fk_trade_account_customer"),
        ]:
            if _table_exists(bind, table) and _has_fk(bind, table, name):
                op.drop_constraint(name, table_name=table, type_="foreignkey")
        for table, name in [
            ("trading_accounts", "uq_trading_account_id_customer"), ("wallets", "uq_wallet_id_customer"), ("trades", "uq_trade_id_customer")
        ]:
            if _table_exists(bind, table) and _has_unique(bind, table, name):
                op.drop_constraint(name, table_name=table, type_="unique")
    if _table_exists(bind, "withdrawal_otp_intents"):
        op.drop_table("withdrawal_otp_intents")
