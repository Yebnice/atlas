"""AtlasRisk 3.10.44: explicit customer execution reserve tracking."""
from alembic import op
import sqlalchemy as sa

revision = "0037_execution_reserve_hardening"
down_revision = "0036_execution_control_plane"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("trades")}
    if "reserved_cash" not in cols:
        op.add_column("trades", sa.Column("reserved_cash", sa.Numeric(38, 18), nullable=False, server_default="0"))

def downgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("trades")}
    if "reserved_cash" in cols:
        op.drop_column("trades", "reserved_cash")
