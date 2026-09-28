"""link adaptive bots to approved strategy candidates

Revision ID: 0028_adaptive_candidate_link
Revises: 0027_strategy_lab_executors
"""
from alembic import op
import sqlalchemy as sa
revision="0028_adaptive_candidate_link"
down_revision="0027_strategy_lab_executors"
branch_labels=None
depends_on=None
def upgrade():
    op.add_column("adaptive_trading_bots", sa.Column("strategy_candidate_id", sa.Integer(), nullable=True))
    op.create_index("ix_adaptive_bot_strategy_candidate_id", "adaptive_trading_bots", ["strategy_candidate_id"])
def downgrade():
    op.drop_index("ix_adaptive_bot_strategy_candidate_id", table_name="adaptive_trading_bots")
    op.drop_column("adaptive_trading_bots", "strategy_candidate_id")
