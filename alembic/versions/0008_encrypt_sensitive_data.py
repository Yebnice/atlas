"""Widen sensitive columns for application-layer authenticated encryption.

Revision ID: 0008_encrypt_sensitive_data
Revises: 0007_customer_withdrawal_wallet_links
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_encrypt_sensitive_data"
down_revision = "0007_customer_withdrawal_wallet_links"
branch_labels = None
depends_on = None


def _textify(table, columns):
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns(table)}
    with op.batch_alter_table(table) as batch:
        for column in columns:
            if column not in existing:
                batch.add_column(sa.Column(column, sa.Text(), nullable=False, server_default=""))
            else:
                batch.alter_column(column, existing_type=sa.String(), type_=sa.Text())


def upgrade():
    _textify("audit_log", ["detail"])
    _textify("withdrawals", ["destination", "destination_tag", "provider_error", "rejection_reason", "local_signature"])
    _textify("customer_profiles", ["email", "display_name"])
    _textify("wallets", ["deposit_address", "token_contract"])
    _textify("funding_transactions", ["metadata_json"])


def downgrade():
    # Encrypted ciphertext is intentionally stored in TEXT-sized columns; shrinking
    # these columns would risk truncation and is therefore not a safe automatic downgrade.
    pass
