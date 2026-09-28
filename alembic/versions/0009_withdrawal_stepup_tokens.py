"""Persist single-use withdrawal OTP step-up tokens."""
from alembic import op
import sqlalchemy as sa

revision = "0009_withdrawal_stepup_tokens"
down_revision = "0008_encrypt_sensitive_data"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "withdrawal_step_up_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("auth_user_id", sa.String(length=120), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False, server_default="withdrawal"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("jti", name="uq_withdrawal_stepup_jti"),
    )
    op.create_index("ix_withdrawal_stepup_customer_expiry", "withdrawal_step_up_tokens", ["auth_user_id", "expires_at"])
    op.create_index("ix_withdrawal_step_up_tokens_auth_user_id", "withdrawal_step_up_tokens", ["auth_user_id"])


def downgrade():
    op.drop_index("ix_withdrawal_step_up_tokens_auth_user_id", table_name="withdrawal_step_up_tokens")
    op.drop_index("ix_withdrawal_stepup_customer_expiry", table_name="withdrawal_step_up_tokens")
    op.drop_table("withdrawal_step_up_tokens")
