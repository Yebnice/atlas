"""Security and billing hardening for 3.10.24."""
from alembic import op
import sqlalchemy as sa

revision = "0023_security_billing_hardening"
down_revision = "0022_binance_customer_subaccounts"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("customer_binance_accounts", sa.Column("enable_withdrawals", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("subscriptions", sa.Column("stripe_last_event_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "stripe_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(length=180), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("stripe_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="RECEIVED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_stripe_webhook_event_id"),
    )
    op.create_index("ix_stripe_webhook_event_created", "stripe_webhook_events", ["created_at"])

def downgrade():
    op.drop_index("ix_stripe_webhook_event_created", table_name="stripe_webhook_events")
    op.drop_table("stripe_webhook_events")
    op.drop_column("subscriptions", "stripe_last_event_at")
    op.drop_column("customer_binance_accounts", "enable_withdrawals")
