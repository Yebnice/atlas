"""AtlasRisk 3.10.43: durable order commands and live execution fencing."""
from alembic import op
import sqlalchemy as sa

revision = "0036_execution_control_plane"
down_revision = "0035_trade_memory_replay"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "order_commands" not in tables:
        op.create_table(
            "order_commands",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("trade_id", sa.Integer(), sa.ForeignKey("trades.id"), nullable=False),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer_profiles.id"), nullable=True),
            sa.Column("exchange", sa.String(50), nullable=False, server_default=""),
            sa.Column("symbol", sa.String(80), nullable=False),
            sa.Column("side", sa.String(10), nullable=False),
            sa.Column("requested_quantity", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("reference_price", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("stop_loss_price", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("take_profit_price", sa.Numeric(38, 18), nullable=False, server_default="0"),
            sa.Column("client_order_id", sa.String(120), nullable=False),
            sa.Column("idempotency_key", sa.String(220), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="READY"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("broker_order_id", sa.String(120), nullable=False, server_default=""),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("trade_id", name="uq_order_command_trade"),
            sa.UniqueConstraint("idempotency_key", name="uq_order_command_idempotency"),
            sa.UniqueConstraint("client_order_id", name="uq_order_command_client_order"),
        )
        op.create_index("ix_order_command_trade_id", "order_commands", ["trade_id"])
        op.create_index("ix_order_command_customer_id", "order_commands", ["customer_id"])
        op.create_index("ix_order_command_status_updated", "order_commands", ["status", "updated_at"])

    if "live_execution_lease" not in tables:
        op.create_table(
            "live_execution_lease",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.String(160), nullable=False, server_default=""),
            sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        # Singleton row: acquisition code locks this row with SELECT FOR UPDATE.
        op.execute(sa.text(
            "INSERT INTO live_execution_lease (id, owner_id, fencing_token, expires_at, updated_at) "
            "VALUES (1, '', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "live_execution_lease" in tables:
        op.drop_table("live_execution_lease")
    if "order_commands" in tables:
        op.drop_index("ix_order_command_status_updated", table_name="order_commands")
        op.drop_index("ix_order_command_customer_id", table_name="order_commands")
        op.drop_index("ix_order_command_trade_id", table_name="order_commands")
        op.drop_table("order_commands")
