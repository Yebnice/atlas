"""Safety hardening: persistent forex demo state.

Revision ID: 0004_safety_hardening
Revises: 0003_payout_execution
"""
from alembic import op
import sqlalchemy as sa
revision = "0004_safety_hardening"
down_revision = "0003_payout_execution"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("app_state", sa.Column("forex_demo_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    op.drop_column("app_state", "forex_demo_enabled")
