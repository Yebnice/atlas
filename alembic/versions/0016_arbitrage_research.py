"""arbitrage research and paper opportunities
Revision ID: 0016_arbitrage_research
Revises: 0015_grid_webhooks_connectors
"""
from alembic import op
import sqlalchemy as sa
revision = "0016_arbitrage_research"
down_revision = "0015_grid_webhooks_connectors"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("arbitrage_opportunities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer()), sa.Column("trading_account_id", sa.Integer()),
        sa.Column("exchange", sa.String(50), nullable=False, server_default="binance"),
        sa.Column("path_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("start_quote", sa.Float(), nullable=False, server_default="0"),
        sa.Column("end_quote", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gross_edge_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fees_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("slippage_buffer_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("safety_buffer_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("net_edge_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="PAPER_CANDIDATE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_arb_customer_created", "arbitrage_opportunities", ["customer_id", "created_at"])
    op.create_index("ix_arb_status", "arbitrage_opportunities", ["status"])

def downgrade():
    op.drop_table("arbitrage_opportunities")
