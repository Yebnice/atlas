from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("app_state",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("cash_equity", sa.Float(), nullable=False, server_default="10000"),
        sa.Column("equity", sa.Float(), nullable=False, server_default="10000"),
        sa.Column("peak_equity", sa.Float(), nullable=False, server_default="10000"),
        sa.Column("daily_start_equity", sa.Float(), nullable=False, server_default="10000"),
        sa.Column("daily_start_date", sa.Date(), nullable=False), sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0"), sa.Column("kill_switch", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("live_enabled", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("trades",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("signal_id", sa.String(160), nullable=False),
        sa.Column("client_order_id", sa.String(120), nullable=False), sa.Column("broker_order_id", sa.String(120), nullable=False, server_default=""),
        sa.Column("exchange", sa.String(50), nullable=False, server_default=""), sa.Column("symbol", sa.String(80), nullable=False), sa.Column("timeframe", sa.String(20), nullable=False, server_default=""),
        sa.Column("side", sa.String(10), nullable=False), sa.Column("quantity", sa.Float(), nullable=False, server_default="0"), sa.Column("requested_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("filled_quantity", sa.Float(), nullable=False, server_default="0"), sa.Column("remaining_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("requested_price", sa.Float(), nullable=False, server_default="0"), sa.Column("average_fill_price", sa.Float(), nullable=False, server_default="0"), sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notional", sa.Float(), nullable=False, server_default="0"), sa.Column("mode", sa.String(20), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""), sa.Column("stop_loss_price", sa.Float(), nullable=False, server_default="0"), sa.Column("take_profit_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True)), sa.Column("updated_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint("uq_trade_client_order_id", "trades", ["client_order_id"])
    op.create_unique_constraint("uq_trade_signal_id", "trades", ["signal_id"])
    op.create_index("ix_trade_status_symbol", "trades", ["status", "symbol"])
    op.create_table("positions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("exchange", sa.String(50), nullable=False, server_default=""), sa.Column("symbol", sa.String(80), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"), sa.Column("average_entry_price", sa.Float(), nullable=False, server_default="0"), sa.Column("mark_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0"), sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0"), sa.Column("updated_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint("uq_position_symbol", "positions", ["symbol"])
    op.create_table("audit_log", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event", sa.String(100), nullable=False), sa.Column("detail", sa.Text(), nullable=False, server_default=""), sa.Column("created_at", sa.DateTime(timezone=True)))


    # Alembic creates alembic_version before running revision 0001. Several historical
    # revision identifiers exceed the default VARCHAR(32); widen it here so a fresh
    # PostgreSQL database can traverse the complete migration chain.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"))
    elif bind.dialect.name == "sqlite":
        with op.batch_alter_table("alembic_version", recreate="always") as batch:
            batch.alter_column("version_num", existing_type=sa.String(length=32), type_=sa.String(length=128))


def downgrade():
    op.drop_table("audit_log")
    op.drop_constraint("uq_position_symbol", "positions", type_="unique")
    op.drop_table("positions")
    op.drop_index("ix_trade_status_symbol", table_name="trades")
    op.drop_constraint("uq_trade_signal_id", "trades", type_="unique")
    op.drop_constraint("uq_trade_client_order_id", "trades", type_="unique")
    op.drop_table("trades")
    op.drop_table("app_state")
