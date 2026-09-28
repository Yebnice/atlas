"""Persist explicit high-risk withdrawal review."""
from alembic import op
import sqlalchemy as sa
revision = "0011_withdrawal_risk_review"
down_revision = "0010_production_distributed_security"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("withdrawals", sa.Column("risk_reviewed_by", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("withdrawals", sa.Column("risk_reviewed_at", sa.DateTime(timezone=True), nullable=True))
def downgrade():
    op.drop_column("withdrawals", "risk_reviewed_at")
    op.drop_column("withdrawals", "risk_reviewed_by")
