"""payout execution and reconciliation fields
Revision ID: 0003_payout_execution
Revises: 0002_withdrawals
"""
from alembic import op
import sqlalchemy as sa
revision = "0003_payout_execution"
down_revision = "0002_withdrawals"
branch_labels = None
depends_on = None

def upgrade():
    for name, typ, default in [
        ("destination", sa.Text(), ""), ("destination_tag", sa.String(120), ""),
        ("network", sa.String(40), ""), ("provider", sa.String(40), ""),
        ("provider_id", sa.String(180), ""), ("provider_status", sa.String(60), ""),
        ("provider_error", sa.Text(), ""),
    ]:
        op.add_column("withdrawals", sa.Column(name, typ, nullable=False, server_default=default))

def downgrade():
    for name in ["provider_error", "provider_status", "provider_id", "provider", "network", "destination_tag", "destination"]:
        op.drop_column("withdrawals", name)
