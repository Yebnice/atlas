"""Atlas 3.10.37 platform hardening: custody integers, RBAC, address policy, audit chain."""
from alembic import op
import sqlalchemy as sa

revision = "0032_platform_hardening"
down_revision = "0031_experiment_tracking_and_drift"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    # TRON block timestamps are milliseconds and exceed PostgreSQL INTEGER.
    # SQLite needs Alembic batch recreation because it cannot ALTER COLUMN TYPE.
    if dialect == "sqlite":
        with op.batch_alter_table("tron_deposit_cursors", recreate="always") as batch:
            batch.alter_column("last_block_timestamp", existing_type=sa.Integer(), type_=sa.BigInteger())
        with op.batch_alter_table("tron_sweeps", recreate="always") as batch:
            batch.alter_column("amount_raw", existing_type=sa.Integer(), type_=sa.BigInteger())
    else:
        op.alter_column("tron_deposit_cursors", "last_block_timestamp", existing_type=sa.Integer(), type_=sa.BigInteger())
        # TRON USDT uses 6-decimal raw units; INTEGER caps a sweep at ~2,147 USDT.
        op.alter_column("tron_sweeps", "amount_raw", existing_type=sa.Integer(), type_=sa.BigInteger())

    op.add_column("audit_log", sa.Column("actor_id", sa.String(length=160), nullable=False, server_default=""))
    op.add_column("audit_log", sa.Column("previous_hash", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("audit_log", sa.Column("event_hash", sa.String(length=64), nullable=False, server_default=""))
    op.create_index("ix_audit_log_created_event", "audit_log", ["created_at", "event"])

    op.create_table(
        "audit_chain_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(sa.text("INSERT INTO audit_chain_state (id, last_hash) VALUES (1, '')"))

    op.create_table(
        "admin_roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("auth_user_id", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("auth_user_id", "role", name="uq_admin_role_user_role"),
    )
    op.create_index("ix_admin_roles_user_active", "admin_roles", ["auth_user_id", "active"])

    op.create_table(
        "withdrawal_destinations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=20), nullable=False),
        sa.Column("network", sa.String(length=40), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("customer_id", "fingerprint", name="uq_withdrawal_destination_customer_fingerprint"),
    )
    op.create_index("ix_withdrawal_destination_customer", "withdrawal_destinations", ["customer_id", "status"])

    # Database invariants. PostgreSQL and SQLite both support these CHECK constraints.
    checks = [
        ("ck_customer_ledger_available_nonnegative", "available >= 0"),
        ("ck_customer_ledger_trading_reserved_nonnegative", "trading_reserved >= 0"),
        ("ck_customer_ledger_withdrawal_reserved_nonnegative", "withdrawal_reserved >= 0"),
        ("ck_ledger_line_debit_nonnegative", "debit >= 0"),
        ("ck_ledger_line_credit_nonnegative", "credit >= 0"),
        ("ck_ledger_line_not_both_sides", "NOT (debit > 0 AND credit > 0)"),
    ]
    if dialect == "sqlite":
        with op.batch_alter_table("customer_ledger_accounts", recreate="always") as batch:
            for name, expr in checks[:3]:
                batch.create_check_constraint(name, expr)
        with op.batch_alter_table("ledger_journal_lines", recreate="always") as batch:
            for name, expr in checks[3:]:
                batch.create_check_constraint(name, expr)
    else:
        for name, expr in checks:
            table = "customer_ledger_accounts" if name.startswith("ck_customer") else "ledger_journal_lines"
            op.create_check_constraint(name, table, expr)

    if dialect == "postgresql":
        # Existing deployments may contain legacy orphan rows. NOT VALID lets the
        # constraint protect new writes immediately; a separate validation step can
        # be run after orphan cleanup.
        for table, col, ref in [
            ("wallets", "customer_id", "customer_profiles(id)"),
            ("customer_ledger_accounts", "customer_id", "customer_profiles(id)"),
            ("withdrawals", "customer_id", "customer_profiles(id)"),
            ("withdrawals", "wallet_id", "wallets(id)"),
            ("tron_deposit_cursors", "wallet_id", "wallets(id)"),
            ("tron_sweeps", "wallet_id", "wallets(id)"),
            ("ledger_journal_lines", "journal_id", "ledger_journals(id)"),
        ]:
            cname = f"fk_{table}_{col}"
            op.execute(sa.text(
                f'ALTER TABLE "{table}" ADD CONSTRAINT "{cname}" FOREIGN KEY ("{col}") REFERENCES {ref} NOT VALID'
            ))


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        for table, col in [
            ("ledger_journal_lines", "journal_id"), ("tron_sweeps", "wallet_id"),
            ("tron_deposit_cursors", "wallet_id"), ("withdrawals", "wallet_id"),
            ("withdrawals", "customer_id"), ("customer_ledger_accounts", "customer_id"),
            ("wallets", "customer_id"),
        ]:
            op.execute(sa.text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "fk_{table}_{col}"'))
    constraint_groups = [
        ("customer_ledger_accounts", ["ck_customer_ledger_available_nonnegative", "ck_customer_ledger_trading_reserved_nonnegative", "ck_customer_ledger_withdrawal_reserved_nonnegative"]),
        ("ledger_journal_lines", ["ck_ledger_line_debit_nonnegative", "ck_ledger_line_credit_nonnegative", "ck_ledger_line_not_both_sides"]),
    ]
    if dialect == "sqlite":
        for table, names in constraint_groups:
            with op.batch_alter_table(table, recreate="always") as batch:
                for name in names:
                    batch.drop_constraint(name, type_="check")
    else:
        for table, names in constraint_groups:
            for name in names:
                op.drop_constraint(name, table_name=table, type_="check")
    op.drop_index("ix_withdrawal_destination_customer", table_name="withdrawal_destinations")
    op.drop_table("withdrawal_destinations")
    op.drop_index("ix_admin_roles_user_active", table_name="admin_roles")
    op.drop_table("admin_roles")
    op.drop_index("ix_audit_log_created_event", table_name="audit_log")
    op.drop_table("audit_chain_state")
    op.drop_column("audit_log", "event_hash")
    op.drop_column("audit_log", "previous_hash")
    op.drop_column("audit_log", "actor_id")
    if dialect == "sqlite":
        with op.batch_alter_table("tron_sweeps", recreate="always") as batch:
            batch.alter_column("amount_raw", existing_type=sa.BigInteger(), type_=sa.Integer())
        with op.batch_alter_table("tron_deposit_cursors", recreate="always") as batch:
            batch.alter_column("last_block_timestamp", existing_type=sa.BigInteger(), type_=sa.Integer())
    else:
        op.alter_column("tron_sweeps", "amount_raw", existing_type=sa.BigInteger(), type_=sa.Integer())
        op.alter_column("tron_deposit_cursors", "last_block_timestamp", existing_type=sa.BigInteger(), type_=sa.Integer())
