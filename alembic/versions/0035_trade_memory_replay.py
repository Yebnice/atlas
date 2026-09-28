"""AtlasRisk 3.10.42: trade memory, replay and counterfactual learning."""
from alembic import op
import sqlalchemy as sa

revision = "0035_trade_memory_replay"
down_revision = "0034_adaptive_strategy_router"
branch_labels = None
depends_on = None


def _add_column_if_missing(bind, table, column):
    cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
    if column.name not in cols:
        op.add_column(table, column)


def upgrade():
    bind = op.get_bind()
    _add_column_if_missing(bind, "strategy_outcomes", sa.Column("net_pnl", sa.Numeric(38, 18), nullable=False, server_default="0"))
    _add_column_if_missing(bind, "strategy_outcomes", sa.Column("net_return_bps", sa.Float(), nullable=False, server_default="0"))

    tables = set(sa.inspect(bind).get_table_names())
    if "trade_learning_episodes" not in tables:
        op.create_table(
            "trade_learning_episodes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("entry_trade_id", sa.Integer(), nullable=False),
            sa.Column("closing_trade_id", sa.Integer(), nullable=True),
            sa.Column("customer_id", sa.Integer(), nullable=True),
            sa.Column("bot_id", sa.Integer(), nullable=True),
            sa.Column("asset", sa.String(20), nullable=False, server_default="crypto"),
            sa.Column("exchange", sa.String(50), nullable=False, server_default=""),
            sa.Column("symbol", sa.String(80), nullable=False, server_default=""),
            sa.Column("timeframe", sa.String(20), nullable=False, server_default=""),
            sa.Column("side", sa.String(10), nullable=False, server_default=""),
            sa.Column("strategy", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("regime", sa.String(40), nullable=False, server_default="UNKNOWN"),
            sa.Column("model_version", sa.String(128), nullable=False, server_default=""),
            sa.Column("entry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("exit_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("entry_quantity", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("entry_price", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("exit_price", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("gross_pnl", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("total_fees", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("net_pnl", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("return_bps", sa.Float(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
            sa.Column("replay_status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("replay_version", sa.String(80), nullable=False, server_default=""),
            sa.Column("replay_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("bars_held", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mfe_bps", sa.Float(), nullable=False, server_default="0"),
            sa.Column("mae_bps", sa.Float(), nullable=False, server_default="0"),
            sa.Column("decision_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("market_flow_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("learning_memory_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("entry_trade_id", name="uq_trade_learning_episode_entry_trade"),
        )
        op.create_index("ix_trade_learning_episode_entry_trade", "trade_learning_episodes", ["entry_trade_id"])
        op.create_index("ix_trade_learning_episode_customer_exit", "trade_learning_episodes", ["customer_id", "exit_at"])
        op.create_index("ix_trade_learning_episode_status_replay", "trade_learning_episodes", ["status", "replay_status"])

    if "trade_replay_results" not in tables:
        op.create_table(
            "trade_replay_results",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("episode_id", sa.Integer(), nullable=False),
            sa.Column("strategy", sa.String(40), nullable=False),
            sa.Column("entry_signal", sa.Float(), nullable=False, server_default="0"),
            sa.Column("entry_side", sa.String(10), nullable=False, server_default="flat"),
            sa.Column("entry_decision_return_bps", sa.Float(), nullable=False, server_default="0"),
            sa.Column("policy_window_return_bps", sa.Float(), nullable=False, server_default="0"),
            sa.Column("confidence", sa.String(20), nullable=False, server_default="LOW"),
            sa.Column("comparison_scope", sa.String(120), nullable=False, server_default=""),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("episode_id", "strategy", name="uq_trade_replay_episode_strategy"),
        )
        op.create_index("ix_trade_replay_episode", "trade_replay_results", ["episode_id"])
        op.create_index("ix_trade_replay_strategy_created", "trade_replay_results", ["strategy", "created_at"])


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "trade_replay_results" in tables:
        op.drop_index("ix_trade_replay_strategy_created", table_name="trade_replay_results")
        op.drop_index("ix_trade_replay_episode", table_name="trade_replay_results")
        op.drop_table("trade_replay_results")
    if "trade_learning_episodes" in tables:
        op.drop_index("ix_trade_learning_episode_status_replay", table_name="trade_learning_episodes")
        op.drop_index("ix_trade_learning_episode_customer_exit", table_name="trade_learning_episodes")
        op.drop_index("ix_trade_learning_episode_entry_trade", table_name="trade_learning_episodes")
        op.drop_table("trade_learning_episodes")
    # Keep added financial outcome columns for backwards-compatible rolling downgrades.
