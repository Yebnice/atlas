"""experiment tracking and drift monitoring tables

Adds persistence that was previously missing entirely:
  - strategy_candidate_runs: history of each validate() attempt on a strategy
    candidate (previously overwritten in place on the candidate row itself).
  - model_experiments: history of each adaptive-model retrain attempt, promoted
    or rejected, including the feature-drift reading that preceded it (previously
    only the current champion's metadata file existed; no history was kept).
  - research_runs: per-symbol daily research output, including a computed
    regime/performance drift comparison against the previous run for that symbol
    (previously the daily research job produced this comparison as an instruction
    to itself in its own output text, but never persisted anything to compare against).

Revision ID: 0031_experiment_tracking_and_drift
Revises: 0030_financial_precision_and_wallet_recovery
"""
from alembic import op
import sqlalchemy as sa

revision = "0031_experiment_tracking_and_drift"
down_revision = "0030_financial_precision_and_wallet_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "strategy_candidate_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("backtest_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("oos_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("gate_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_strategy_candidate_run_candidate", "strategy_candidate_runs", ["candidate_id", "created_at"])

    op.create_table(
        "model_experiments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_path", sa.String(400), nullable=False),
        sa.Column("asset", sa.String(20), nullable=False, server_default="crypto"),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("model_sha256", sa.String(128), nullable=False, server_default=""),
        sa.Column("gate_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("wfo_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("feature_drift_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_experiment_path_created", "model_experiments", ["model_path", "created_at"])
    op.create_index("ix_model_experiment_model_path", "model_experiments", ["model_path"])

    op.create_table(
        "research_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(80), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("regime_assessment", sa.String(60), nullable=False, server_default=""),
        sa.Column("top_strategy", sa.String(40), nullable=False, server_default=""),
        sa.Column("sharpe", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_drawdown", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_return", sa.Float(), nullable=False, server_default="0"),
        sa.Column("regime_drift_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("research_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("review_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_run_symbol_created", "research_runs", ["symbol", "created_at"])
    op.create_index("ix_research_run_symbol", "research_runs", ["symbol"])


def downgrade():
    op.drop_index("ix_research_run_symbol", table_name="research_runs")
    op.drop_index("ix_research_run_symbol_created", table_name="research_runs")
    op.drop_table("research_runs")

    op.drop_index("ix_model_experiment_model_path", table_name="model_experiments")
    op.drop_index("ix_model_experiment_path_created", table_name="model_experiments")
    op.drop_table("model_experiments")

    op.drop_index("ix_strategy_candidate_run_candidate", table_name="strategy_candidate_runs")
    op.drop_table("strategy_candidate_runs")
