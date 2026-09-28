"""AtlasRisk 3.10.41: regime-aware adaptive strategy router and outcome memory."""
from alembic import op
import sqlalchemy as sa

revision = "0034_adaptive_strategy_router"
down_revision = "0033_live_money_hardening"
branch_labels = None
depends_on = None


def _add_column_if_missing(bind, table, column):
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns(table)}
    if column.name not in cols:
        op.add_column(table, column)


def upgrade():
    bind = op.get_bind()
    _add_column_if_missing(bind, "adaptive_trading_bots", sa.Column("active_strategy", sa.String(40), nullable=False, server_default=""))
    _add_column_if_missing(bind, "adaptive_trading_bots", sa.Column("active_regime", sa.String(40), nullable=False, server_default=""))
    _add_column_if_missing(bind, "adaptive_trading_bots", sa.Column("strategy_last_switched_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing(bind, "adaptive_trading_bots", sa.Column("strategy_switch_count", sa.Integer(), nullable=False, server_default="0"))
    _add_column_if_missing(bind, "adaptive_trading_bots", sa.Column("strategy_selection_json", sa.Text(), nullable=False, server_default="{}"))

    if "strategy" not in {c["name"] for c in sa.inspect(bind).get_columns("positions")}:
        op.add_column("positions", sa.Column("strategy", sa.String(40), nullable=False, server_default=""))
    if "entry_regime" not in {c["name"] for c in sa.inspect(bind).get_columns("positions")}:
        op.add_column("positions", sa.Column("entry_regime", sa.String(40), nullable=False, server_default=""))

    if "strategy_outcomes" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "strategy_outcomes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("trade_id", sa.Integer(), nullable=False),
            sa.Column("closing_trade_id", sa.Integer(), nullable=True),
            sa.Column("customer_id", sa.Integer(), nullable=True),
            sa.Column("bot_id", sa.Integer(), nullable=True),
            sa.Column("strategy", sa.String(40), nullable=False),
            sa.Column("regime", sa.String(40), nullable=False, server_default="UNKNOWN"),
            sa.Column("asset", sa.String(20), nullable=False, server_default="crypto"),
            sa.Column("symbol", sa.String(80), nullable=False, server_default=""),
            sa.Column("timeframe", sa.String(20), nullable=False, server_default=""),
            sa.Column("side", sa.String(10), nullable=False, server_default=""),
            sa.Column("realized_pnl", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("fee", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("return_bps", sa.Float(), nullable=False, server_default="0"),
            sa.Column("mode", sa.String(20), nullable=False, server_default=""),
            sa.Column("sequence", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("model_version", sa.String(128), nullable=False, server_default=""),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("trade_id", "sequence", name="uq_strategy_outcome_trade_sequence"),
        )
        op.create_index("ix_strategy_outcome_customer_strategy_created", "strategy_outcomes", ["customer_id", "strategy", "created_at"])
        op.create_index("ix_strategy_outcome_symbol_regime_created", "strategy_outcomes", ["symbol", "regime", "created_at"])
        op.create_index("ix_strategy_outcome_trade", "strategy_outcomes", ["trade_id"])
        op.create_index("ix_strategy_outcome_closing_trade", "strategy_outcomes", ["closing_trade_id"])

    # Defensive additions for a database that created strategy_outcomes from an early
    # 3.10.41 candidate before asset/timeframe attribution was included.
    if "strategy_outcomes" in sa.inspect(bind).get_table_names():
        cols = {c["name"] for c in sa.inspect(bind).get_columns("strategy_outcomes")}
        if "asset" not in cols:
            op.add_column("strategy_outcomes", sa.Column("asset", sa.String(20), nullable=False, server_default="crypto"))
        if "timeframe" not in cols:
            op.add_column("strategy_outcomes", sa.Column("timeframe", sa.String(20), nullable=False, server_default=""))


def downgrade():
    bind = op.get_bind()
    if "strategy_outcomes" in sa.inspect(bind).get_table_names():
        op.drop_index("ix_strategy_outcome_closing_trade", table_name="strategy_outcomes")
        op.drop_index("ix_strategy_outcome_trade", table_name="strategy_outcomes")
        op.drop_index("ix_strategy_outcome_symbol_regime_created", table_name="strategy_outcomes")
        op.drop_index("ix_strategy_outcome_customer_strategy_created", table_name="strategy_outcomes")
        op.drop_table("strategy_outcomes")
