"""withdrawal approval workflow

Revision ID: 0002_withdrawals
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_withdrawals"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "withdrawals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(120), nullable=False),
        sa.Column("account_ref", sa.String(120), nullable=False, server_default=""),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(20), nullable=False, server_default="USD"),
        sa.Column("destination_masked", sa.String(180), nullable=False, server_default=""),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("risk_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("risk_flags", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("required_approvals", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("approval_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_approved_by", sa.String(120), nullable=False, server_default=""),
        sa.Column("first_approved_at", sa.DateTime(timezone=True)),
        sa.Column("second_approved_by", sa.String(120), nullable=False, server_default=""),
        sa.Column("second_approved_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_by", sa.String(120), nullable=False, server_default=""),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("request_id", name="uq_withdrawal_request_id"),
    )
    op.create_index("ix_withdrawal_status_created", "withdrawals", ["status", "created_at"])

def downgrade():
    op.drop_index("ix_withdrawal_status_created", table_name="withdrawals")
    op.drop_table("withdrawals")
