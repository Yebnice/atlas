"""grid bots, authenticated webhooks and connector registry
Revision ID: 0015_grid_webhooks_connectors
Revises: 0014_trading_product_features
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_grid_webhooks_connectors"
down_revision = "0014_trading_product_features"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("grid_bots", sa.Column("id",sa.Integer(),primary_key=True), sa.Column("customer_id",sa.Integer(),nullable=False), sa.Column("trading_account_id",sa.Integer(),nullable=False), sa.Column("exchange",sa.String(50),nullable=False,server_default=""), sa.Column("symbol",sa.String(80),nullable=False), sa.Column("grid_type",sa.String(20),nullable=False,server_default="NEUTRAL"), sa.Column("lower_price",sa.Float(),nullable=False,server_default="0"), sa.Column("upper_price",sa.Float(),nullable=False,server_default="0"), sa.Column("levels",sa.Integer(),nullable=False,server_default="20"), sa.Column("arithmetic",sa.Boolean(),nullable=False,server_default=sa.false()), sa.Column("quote_per_grid",sa.Float(),nullable=False,server_default="0"), sa.Column("take_profit_pct",sa.Float(),nullable=False,server_default="0"), sa.Column("stop_loss_pct",sa.Float(),nullable=False,server_default="0"), sa.Column("trailing_stop_pct",sa.Float(),nullable=False,server_default="0"), sa.Column("status",sa.String(30),nullable=False,server_default="STOPPED"), sa.Column("mode",sa.String(20),nullable=False,server_default="PAPER"), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_grid_bot_customer_status","grid_bots",["customer_id","status"])
    op.create_index("ix_grid_bot_customer","grid_bots",["customer_id"])
    op.create_table("webhook_endpoints", sa.Column("id",sa.Integer(),primary_key=True), sa.Column("customer_id",sa.Integer(),nullable=False), sa.Column("name",sa.String(100),nullable=False,server_default="TradingView"), sa.Column("secret_hash",sa.String(64),nullable=False), sa.Column("status",sa.String(20),nullable=False,server_default="ACTIVE"), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False), sa.Column("last_used_at",sa.DateTime(timezone=True)))
    op.create_unique_constraint("uq_webhook_customer_name","webhook_endpoints",["customer_id","name"])
    op.create_index("ix_webhook_customer_status","webhook_endpoints",["customer_id","status"])
    op.create_table("webhook_events", sa.Column("id",sa.Integer(),primary_key=True), sa.Column("endpoint_id",sa.Integer(),nullable=False), sa.Column("event_id",sa.String(160),nullable=False), sa.Column("payload_json",sa.Text(),nullable=False,server_default="{}"), sa.Column("status",sa.String(30),nullable=False,server_default="RECEIVED"), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_unique_constraint("uq_webhook_endpoint_event","webhook_events",["endpoint_id","event_id"])
    op.create_index("ix_webhook_event_endpoint_created","webhook_events",["endpoint_id","created_at"])
    op.create_table("exchange_connectors", sa.Column("id",sa.Integer(),primary_key=True), sa.Column("name",sa.String(50),nullable=False), sa.Column("market_types",sa.String(120),nullable=False,server_default="spot"), sa.Column("capabilities_json",sa.Text(),nullable=False,server_default="{}"), sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.true()), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_unique_constraint("uq_exchange_connector_name","exchange_connectors",["name"])
    connectors={
      "binance":("spot,swap","{\"orders\":true,\"websocket\":true,\"stop_orders\":true}"),
      "bybit":("spot,swap","{\"orders\":true,\"websocket\":true,\"stop_orders\":true}"),
      "okx":("spot,swap","{\"orders\":true,\"websocket\":true,\"stop_orders\":true}"),
      "bitget":("spot,swap","{\"orders\":true,\"websocket\":true,\"stop_orders\":true}"),
      "kraken":("spot,swap","{\"orders\":true,\"websocket\":true,\"stop_orders\":true}"),
      "coinbase":("spot","{\"orders\":true,\"websocket\":true,\"stop_orders\":true}"),
      "kucoin":("spot,swap","{\"orders\":true,\"websocket\":true,\"stop_orders\":true}"),
      "hyperliquid":("spot,swap","{\"orders\":true,\"websocket\":true,\"stop_orders\":true}"),
    }
    table=sa.table("exchange_connectors", sa.column("name",sa.String), sa.column("market_types",sa.String), sa.column("capabilities_json",sa.Text))
    op.bulk_insert(table,[{"name":k,"market_types":v[0],"capabilities_json":v[1]} for k,v in connectors.items()])


def downgrade():
    for t in ["exchange_connectors","webhook_events","webhook_endpoints","grid_bots"]: op.drop_table(t)
