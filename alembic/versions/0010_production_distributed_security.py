"""Production distributed security and recovery state."""
from alembic import op
import sqlalchemy as sa

revision = "0010_production_distributed_security"
down_revision = "0009_withdrawal_stepup_tokens"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "service_heartbeats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("instance_id", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False, server_default="api"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="READY"),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("instance_id", name="uq_service_heartbeat_instance"),
    )
    op.create_index("ix_service_heartbeat_updated", "service_heartbeats", ["updated_at"])

def downgrade():
    op.drop_index("ix_service_heartbeat_updated", table_name="service_heartbeats")
    op.drop_table("service_heartbeats")
