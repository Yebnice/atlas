"""explicit live approval for executors
Revision ID: 0029_executor_live_approval
Revises: 0028_adaptive_candidate_link
"""
from alembic import op
import sqlalchemy as sa
revision="0029_executor_live_approval"
down_revision="0028_adaptive_candidate_link"
branch_labels=None
depends_on=None
def upgrade():
    op.add_column("trade_executors", sa.Column("mode", sa.String(20), nullable=False, server_default="PAPER"))
    op.add_column("trade_executors", sa.Column("live_approved", sa.Boolean(), nullable=False, server_default=sa.false()))
def downgrade():
    op.drop_column("trade_executors", "live_approved")
    op.drop_column("trade_executors", "mode")
