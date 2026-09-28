"""AtlasRisk 3.10.45: validate legacy FKs and enforce immutable balanced ledger journals."""
from alembic import op
import sqlalchemy as sa

revision = "0040_database_integrity_and_ledger_immutability"
down_revision = "0039_otp_and_customer_ownership_hardening"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Convert every NOT VALID foreign key left by the hardening migrations into a fully
    # validated constraint. This deliberately fails the deployment when legacy orphan rows
    # exist instead of silently declaring the schema safe.
    rows = bind.execute(sa.text("""
        SELECT n.nspname AS schema_name, c.relname AS table_name, con.conname
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE con.contype = 'f' AND NOT con.convalidated
          AND n.nspname = current_schema()
        ORDER BY c.relname, con.conname
    """)).mappings().all()
    for row in rows:
        table = str(row["table_name"]).replace('"', '""')
        name = str(row["conname"]).replace('"', '""')
        op.execute(sa.text(f'ALTER TABLE "{table}" VALIDATE CONSTRAINT "{name}"'))

    # Financial invariants at the database boundary. These complement the application-level
    # Decimal checks and make direct SQL corruption materially harder.
    checks = [
        ("ledger_journal_lines", "ck_ledger_line_amount_scale", "debit = round(debit, 6) AND credit = round(credit, 6)"),
        ("ledger_entries", "ck_ledger_entry_debit_nonnegative", "debit >= 0"),
        ("ledger_entries", "ck_ledger_entry_credit_nonnegative", "credit >= 0"),
        ("ledger_entries", "ck_ledger_entry_not_both_sides", "NOT (debit > 0 AND credit > 0)"),
        ("ledger_entries", "ck_ledger_entry_amount_positive", "amount > 0"),
        ("ledger_entries", "ck_ledger_entry_amount_matches_side", "(debit = amount AND credit = 0) OR (credit = amount AND debit = 0)"),
    ]
    for table, name, expression in checks:
        exists = bind.execute(sa.text("""
            SELECT 1 FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema() AND c.relname = :table AND con.conname = :name
        """), {"table": table, "name": name}).scalar()
        if not exists:
            op.execute(sa.text(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" CHECK ({expression})'))

    # Ledger journals are append-only. Balance and currency consistency are checked at commit
    # by a deferred constraint trigger so a multi-line journal can be assembled inside one tx.
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION atlas_validate_ledger_journal(p_journal_id integer)
        RETURNS void AS $$
        DECLARE
            v_debit numeric := 0;
            v_credit numeric := 0;
            v_lines integer := 0;
            v_currency text;
            v_currency_mismatch integer := 0;
        BEGIN
            SELECT currency INTO v_currency FROM ledger_journals WHERE id = p_journal_id;
            IF NOT FOUND THEN
                RETURN;
            END IF;
            SELECT COUNT(*), COALESCE(SUM(debit),0), COALESCE(SUM(credit),0),
                   COUNT(*) FILTER (WHERE currency <> v_currency)
            INTO v_lines, v_debit, v_credit, v_currency_mismatch
            FROM ledger_journal_lines WHERE journal_id = p_journal_id;
            IF v_lines < 2 OR v_debit <= 0 OR v_debit <> v_credit OR v_currency_mismatch > 0 THEN
                RAISE EXCEPTION 'Unbalanced or invalid ledger journal %', p_journal_id;
            END IF;
        END;
        $$ LANGUAGE plpgsql;

        CREATE OR REPLACE FUNCTION atlas_ledger_journal_deferred_check()
        RETURNS trigger AS $$
        BEGIN
            PERFORM atlas_validate_ledger_journal(COALESCE(NEW.journal_id, OLD.journal_id));
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_ledger_journal_deferred_check ON ledger_journals;
        CREATE CONSTRAINT TRIGGER trg_ledger_journal_deferred_check
        AFTER INSERT OR UPDATE OR DELETE ON ledger_journals
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION atlas_ledger_journal_deferred_check();

        DROP TRIGGER IF EXISTS trg_ledger_line_deferred_check ON ledger_journal_lines;
        CREATE CONSTRAINT TRIGGER trg_ledger_line_deferred_check
        AFTER INSERT OR UPDATE OR DELETE ON ledger_journal_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION atlas_ledger_journal_deferred_check();

        CREATE OR REPLACE FUNCTION atlas_block_ledger_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Ledger journal records are immutable';
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_ledger_journal_immutable ON ledger_journals;
        CREATE TRIGGER trg_ledger_journal_immutable
        BEFORE UPDATE OR DELETE ON ledger_journals
        FOR EACH ROW EXECUTE FUNCTION atlas_block_ledger_mutation();

        DROP TRIGGER IF EXISTS trg_ledger_line_immutable ON ledger_journal_lines;
        CREATE TRIGGER trg_ledger_line_immutable
        BEFORE UPDATE OR DELETE ON ledger_journal_lines
        FOR EACH ROW EXECUTE FUNCTION atlas_block_ledger_mutation();

        DROP TRIGGER IF EXISTS trg_ledger_entry_immutable ON ledger_entries;
        CREATE TRIGGER trg_ledger_entry_immutable
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION atlas_block_ledger_mutation();
    """))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ledger_entry_immutable ON ledger_entries"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ledger_line_immutable ON ledger_journal_lines"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ledger_journal_immutable ON ledger_journals"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ledger_line_deferred_check ON ledger_journal_lines"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ledger_journal_deferred_check ON ledger_journals"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS atlas_block_ledger_mutation()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS atlas_ledger_journal_deferred_check()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS atlas_validate_ledger_journal(integer)"))
    for table, name in [
        ("ledger_journal_lines", "ck_ledger_line_amount_scale"),
        ("ledger_entries", "ck_ledger_entry_debit_nonnegative"),
        ("ledger_entries", "ck_ledger_entry_credit_nonnegative"),
        ("ledger_entries", "ck_ledger_entry_not_both_sides"),
        ("ledger_entries", "ck_ledger_entry_amount_positive"),
        ("ledger_entries", "ck_ledger_entry_amount_matches_side"),
    ]:
        op.execute(sa.text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"'))
