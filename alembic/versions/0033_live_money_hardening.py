"""Atlas 3.10.38 live-money hardening: incidents, token binding, migration repair."""
from alembic import op
import sqlalchemy as sa

revision = "0033_live_money_hardening"
down_revision = "0032_platform_hardening"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind(); dialect = bind.dialect.name
    # Existing databases may already have the wider version column from a repaired deployment.
    if dialect == "postgresql":
        op.execute(sa.text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"))
    elif dialect == "sqlite":
        with op.batch_alter_table("alembic_version", recreate="always") as batch:
            batch.alter_column("version_num", existing_type=sa.String(length=32), type_=sa.String(length=128))

    insp = sa.inspect(bind)
    token_cols = {c["name"] for c in insp.get_columns("withdrawal_step_up_tokens")}
    if "destination_fingerprint" not in token_cols:
        op.add_column("withdrawal_step_up_tokens", sa.Column("destination_fingerprint", sa.String(64), nullable=False, server_default=""))

    for table in ("customer_oanda_accounts", "customer_deriv_accounts"):
        cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        if "scope_status" not in cols:
            op.add_column(table, sa.Column("scope_status", sa.String(60), nullable=False, server_default="UNVERIFIED"))

    if "incidents" not in insp.get_table_names():
        op.create_table(
            "incidents",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("incident_key", sa.String(180), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False, server_default="MEDIUM"),
            sa.Column("status", sa.String(30), nullable=False, server_default="OPEN"),
            sa.Column("category", sa.String(60), nullable=False, server_default="SYSTEM"),
            sa.Column("customer_id", sa.Integer(), nullable=True),
            sa.Column("summary", sa.String(500), nullable=False, server_default=""),
            sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_by", sa.String(160), nullable=False, server_default=""),
            sa.UniqueConstraint("incident_key", name="uq_incident_key"),
        )
        op.create_index("ix_incident_status_severity_created", "incidents", ["status", "severity", "opened_at"])
        op.create_index("ix_incident_customer_status", "incidents", ["customer_id", "status"])

    # Fresh PostgreSQL builds of historical migration 0008 may encounter a missing
    # local_signature column; add it defensively for already-existing deployments.
    withdrawal_cols = {c["name"] for c in sa.inspect(bind).get_columns("withdrawals")}
    if "local_signature" not in withdrawal_cols:
        op.add_column("withdrawals", sa.Column("local_signature", sa.Text(), nullable=False, server_default=""))


def downgrade():
    bind = op.get_bind()
    if "incidents" in sa.inspect(bind).get_table_names():
        op.drop_index("ix_incident_customer_status", table_name="incidents")
        op.drop_index("ix_incident_status_severity_created", table_name="incidents")
        op.drop_table("incidents")
    if "destination_fingerprint" in {c["name"] for c in sa.inspect(bind).get_columns("withdrawal_step_up_tokens")}:
        op.drop_column("withdrawal_step_up_tokens", "destination_fingerprint")
    for table in ("customer_oanda_accounts", "customer_deriv_accounts"):
        if "scope_status" in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            op.drop_column(table, "scope_status")
