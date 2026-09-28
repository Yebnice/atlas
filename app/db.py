from datetime import date, datetime, timezone
from sqlalchemy import String, Float, Boolean, DateTime, Integer, BigInteger, Text, UniqueConstraint, Index, Numeric, ForeignKey, ForeignKeyConstraint
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from .config import settings
from .crypto import encrypt_text, decrypt_text


def _utc_date():
    return datetime.now(timezone.utc).date()

engine_kwargs = {"future": True, "pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs.update({
        "pool_size": 10, "max_overflow": 20, "pool_recycle": 1800,
        "connect_args": {
            "command_timeout": 30,
            "statement_cache_size": 0,
            "server_settings": {
                "statement_timeout": "30000",
                "lock_timeout": "5000",
                "idle_in_transaction_session_timeout": "60000",
            },
        },
    })

engine = create_async_engine(settings.database_url, **engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


class EncryptedText(TypeDecorator):
    """Transparent authenticated encryption for sensitive DB strings."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_text(value)

    def process_result_value(self, value, dialect):
        return decrypt_text(value)


class FinancialNumeric(TypeDecorator):
    """Exact NUMERIC storage with legacy-compatible float materialization.

    Custodial ledger operations explicitly convert to Decimal before arithmetic. The broader
    trading models still expose floats because strategy/execution code performs mixed numerical
    calculations; switching every model field to Decimal without a complete arithmetic migration
    would introduce runtime TypeErrors. Database storage remains PostgreSQL NUMERIC(38,18).
    """
    impl = Numeric(38, 18, asdecimal=False)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        d = value if isinstance(value, Decimal) else Decimal(str(value))
        if not d.is_finite():
            raise ValueError("financial values must be finite")
        return d

    def process_result_value(self, value, dialect):
        return None if value is None else float(value)


def quantize_money(*values: float, places: int = 8) -> float:
    """Round a float-typed FinancialNumeric value through Decimal to bound float-drift.

    This does not make the field Decimal end-to-end -- it only prevents each individual
    arithmetic step on a FinancialNumeric-backed field from carrying more spurious precision
    than the value can actually represent, so drift can't silently accumulate across many
    sequential operations on the same field (e.g. many trades' worth of fee deductions).
    Returns a single float for one input value (for inline use in an assignment), or a tuple
    of floats when called with several values at once.
    """
    q = Decimal(1).scaleb(-places)
    results = [float(Decimal(str(v)).quantize(q)) for v in values]
    return results[0] if len(results) == 1 else tuple(results)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppState(Base):
    __tablename__ = "app_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    mode: Mapped[str] = mapped_column(String(20), default="PAPER")
    cash_equity: Mapped[float] = mapped_column(FinancialNumeric, default=settings.initial_equity)
    equity: Mapped[float] = mapped_column(FinancialNumeric, default=settings.initial_equity)
    peak_equity: Mapped[float] = mapped_column(FinancialNumeric, default=settings.initial_equity)
    daily_start_equity: Mapped[float] = mapped_column(FinancialNumeric, default=settings.initial_equity)
    daily_start_date: Mapped[date] = mapped_column(default=_utc_date)
    realized_pnl: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    live_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    forex_demo_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OandaReconciliationState(Base):
    __tablename__ = "oanda_reconciliation_state"
    __table_args__ = (UniqueConstraint("account_id", name="uq_oanda_reconciliation_account"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    last_transaction_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="practice")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="READY")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)


class TradingAccount(Base):
    __tablename__ = "trading_accounts"
    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_trading_account_customer"),
        UniqueConstraint("id", "customer_id", name="uq_trading_account_id_customer"),
        Index("ix_trading_account_status", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(20), default="USDT")
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    cash_equity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    equity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    peak_equity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    daily_start_equity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    daily_start_date: Mapped[date] = mapped_column(default=_utc_date)
    realized_pnl: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    reserved_margin: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)



class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_trade_client_order_id"),
        UniqueConstraint("signal_id", name="uq_trade_signal_id"),
        UniqueConstraint("id", "customer_id", name="uq_trade_id_customer"),
        ForeignKeyConstraint(["trading_account_id", "customer_id"], ["trading_accounts.id", "trading_accounts.customer_id"], name="fk_trade_account_customer"),
        Index("ix_trade_status_symbol", "status", "symbol"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customer_profiles.id"), nullable=True, index=True)
    trading_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    signal_id: Mapped[str] = mapped_column(String(160), nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(120), nullable=False)
    broker_order_id: Mapped[str] = mapped_column(String(120), default="")
    exchange: Mapped[str] = mapped_column(String(50), default="")
    symbol: Mapped[str] = mapped_column(String(80))
    timeframe: Mapped[str] = mapped_column(String(20), default="")
    side: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    requested_quantity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    filled_quantity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    remaining_quantity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    requested_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    reserved_cash: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    average_fill_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    fee: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    notional: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    stop_loss_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    take_profit_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OrderCommand(Base):
    __tablename__ = "order_commands"
    __table_args__ = (
        UniqueConstraint("trade_id", name="uq_order_command_trade"),
        UniqueConstraint("idempotency_key", name="uq_order_command_idempotency"),
        UniqueConstraint("client_order_id", name="uq_order_command_client_order"),
        ForeignKeyConstraint(["trade_id", "customer_id"], ["trades.id", "trades.customer_id"], name="fk_order_command_trade_customer"),
        Index("ix_order_command_status_updated", "status", "updated_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    exchange: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    requested_quantity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    reference_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    stop_loss_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    take_profit_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    client_order_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="READY")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    broker_order_id: Mapped[str] = mapped_column(String(120), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LiveExecutionLease(Base):
    __tablename__ = "live_execution_lease"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("customer_id", "exchange", "symbol", name="uq_position_customer_exchange_symbol"),
        ForeignKeyConstraint(["trading_account_id", "customer_id"], ["trading_accounts.id", "trading_accounts.customer_id"], name="fk_position_account_customer"),
        ForeignKeyConstraint(["entry_trade_id", "customer_id"], ["trades.id", "trades.customer_id"], name="fk_position_trade_customer"),
        Index("ix_position_customer_status", "customer_id", "quantity"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    trading_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    exchange: Mapped[str] = mapped_column(String(50), default="")
    symbol: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)  # signed: + long, - short
    average_entry_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    mark_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    reserved_capital: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    strategy: Mapped[str] = mapped_column(String(40), default="")
    entry_regime: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    entry_trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(EncryptedText, default="")
    actor_id: Mapped[str] = mapped_column(String(160), default="")
    previous_hash: Mapped[str] = mapped_column(String(64), default="")
    event_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditChainState(Base):
    __tablename__ = "audit_chain_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_hash: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AdminRole(Base):
    __tablename__ = "admin_roles"
    __table_args__ = (UniqueConstraint("auth_user_id", "role", name="uq_admin_role_user_role"), Index("ix_admin_roles_user_active", "auth_user_id", "active"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    auth_user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WithdrawalDestination(Base):
    __tablename__ = "withdrawal_destinations"
    __table_args__ = (UniqueConstraint("customer_id", "fingerprint", name="uq_withdrawal_destination_customer_fingerprint"), Index("ix_withdrawal_destination_customer", "customer_id", "status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(20), nullable=False)
    network: Mapped[str] = mapped_column(String(40), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incident_status_severity_created", "status", "severity", "opened_at"), Index("ix_incident_customer_status", "customer_id", "status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_key: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="SYSTEM")
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    detail_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str] = mapped_column(String(160), default="")


class WithdrawalStepUpToken(Base):
    __tablename__ = "withdrawal_step_up_tokens"
    __table_args__ = (
        UniqueConstraint("jti", name="uq_withdrawal_stepup_jti"),
        Index("ix_withdrawal_stepup_customer_expiry", "auth_user_id", "expires_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    jti: Mapped[str] = mapped_column(String(64), nullable=False)
    auth_user_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, default="withdrawal")
    destination_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    proposal_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WithdrawalOtpIntent(Base):
    __tablename__ = "withdrawal_otp_intents"
    __table_args__ = (
        UniqueConstraint("jti", name="uq_withdrawal_otp_intent_jti"),
        Index("ix_withdrawal_otp_intent_user_expiry", "auth_user_id", "expires_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String(64), nullable=False)
    auth_user_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    contact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    proposal_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"
    __table_args__ = (UniqueConstraint("instance_id", name="uq_service_heartbeat_instance"), Index("ix_service_heartbeat_updated", "updated_at"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(40), default="api")
    status: Mapped[str] = mapped_column(String(30), default="READY")
    detail: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Withdrawal(Base):
    __tablename__ = "withdrawals"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_withdrawal_request_id"),
        ForeignKeyConstraint(["wallet_id", "customer_id"], ["wallets.id", "wallets.customer_id"], name="fk_withdrawal_wallet_customer"),
        Index("ix_withdrawal_status_created", "status", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    wallet_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    account_ref: Mapped[str] = mapped_column(String(120), default="")
    amount: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    currency: Mapped[str] = mapped_column(String(20), default="USD")
    destination_masked: Mapped[str] = mapped_column(String(180), default="")
    destination: Mapped[str] = mapped_column(EncryptedText, default="")
    destination_tag: Mapped[str] = mapped_column(EncryptedText, default="")
    network: Mapped[str] = mapped_column(String(40), default="")
    provider: Mapped[str] = mapped_column(String(40), default="")
    provider_id: Mapped[str] = mapped_column(String(180), default="")
    provider_status: Mapped[str] = mapped_column(String(60), default="")
    provider_error: Mapped[str] = mapped_column(EncryptedText, default="")
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_flags: Mapped[str] = mapped_column(Text, default="[]")
    required_approvals: Mapped[int] = mapped_column(Integer, default=2)
    approval_count: Mapped[int] = mapped_column(Integer, default=0)
    first_approved_by: Mapped[str] = mapped_column(String(120), default="")
    first_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    second_approved_by: Mapped[str] = mapped_column(String(120), default="")
    second_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[str] = mapped_column(String(120), default="")
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str] = mapped_column(EncryptedText, default="")
    proposal_digest: Mapped[str] = mapped_column(String(64), default="")
    execution_operator: Mapped[str] = mapped_column(String(120), default="")
    execution_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    local_signature: Mapped[str] = mapped_column(EncryptedText, default="")
    risk_reviewed_by: Mapped[str] = mapped_column(String(120), default="")
    risk_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        state = await db.get(AppState, 1)
        if not state:
            db.add(AppState(
                cash_equity=settings.initial_equity,
                equity=settings.initial_equity,
                peak_equity=settings.initial_equity,
                daily_start_equity=settings.initial_equity,
                daily_start_date=_utc_date(),
            ))
            await db.commit()

class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    __table_args__ = (UniqueConstraint("auth_user_id", name="uq_customer_auth_user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    auth_user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(EncryptedText, default="")
    display_name: Mapped[str] = mapped_column(EncryptedText, default="")
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (UniqueConstraint("customer_id", "currency", name="uq_wallet_customer_currency"),
        UniqueConstraint("id", "customer_id", name="uq_wallet_id_customer"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(20), nullable=False)
    wallet_type: Mapped[str] = mapped_column(String(40), default="TRADING")
    network: Mapped[str] = mapped_column(String(40), default="")
    deposit_address: Mapped[str] = mapped_column(EncryptedText, default="")
    token_contract: Mapped[str] = mapped_column(EncryptedText, default="")
    derivation_path: Mapped[str] = mapped_column(String(100), default="")
    available_balance: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    locked_balance: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CustomerLedgerAccount(Base):
    __tablename__ = "customer_ledger_accounts"
    __table_args__ = (
        UniqueConstraint("customer_id", "currency", name="uq_customer_ledger_account_currency"),
        Index("ix_customer_ledger_account_customer", "customer_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(20), nullable=False, default="USDT")
    available: Mapped[float] = mapped_column(Numeric(38, 6), nullable=False, default=0)
    trading_reserved: Mapped[float] = mapped_column(Numeric(38, 6), nullable=False, default=0)
    withdrawal_reserved: Mapped[float] = mapped_column(Numeric(38, 6), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LedgerJournal(Base):
    __tablename__ = "ledger_journals"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ledger_journal_idempotency"),
        Index("ix_ledger_journal_reference", "reference_type", "reference_id"),
        Index("ix_ledger_journal_created", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    currency: Mapped[str] = mapped_column(String(20), nullable=False, default="USDT")
    entry_type: Mapped[str] = mapped_column(String(60), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    reference_id: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LedgerJournalLine(Base):
    __tablename__ = "ledger_journal_lines"
    __table_args__ = (
        UniqueConstraint("journal_id", "line_no", name="uq_ledger_journal_line_no"),
        Index("ix_ledger_journal_line_account", "account_code"),
        Index("ix_ledger_journal_line_customer", "customer_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_code: Mapped[str] = mapped_column(String(180), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(20), nullable=False, default="USDT")
    debit: Mapped[float] = mapped_column(Numeric(38, 6), nullable=False, default=0)
    credit: Mapped[float] = mapped_column(Numeric(38, 6), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ledger_entry_idempotency"),
        Index("ix_ledger_entry_customer_created", "customer_id", "created_at"),
        Index("ix_ledger_entry_reference", "reference_type", "reference_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(20), nullable=False, default="USDT")
    entry_type: Mapped[str] = mapped_column(String(40), nullable=False)
    debit: Mapped[float] = mapped_column(Numeric(38, 6), nullable=False, default=0)
    credit: Mapped[float] = mapped_column(Numeric(38, 6), nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Numeric(38, 6), nullable=False, default=0)
    reference_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    reference_id: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    metadata_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Plan(Base):
    __tablename__ = "billing_plans"
    __table_args__ = (UniqueConstraint("code", name="uq_billing_plan_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    monthly_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    annual_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    ai_credits: Mapped[int] = mapped_column(Integer, default=0)
    exchange_connections: Mapped[int] = mapped_column(Integer, default=0)
    active_strategies: Mapped[int] = mapped_column(Integer, default=0)
    live_trading: Mapped[bool] = mapped_column(Boolean, default=False)
    paper_trading: Mapped[bool] = mapped_column(Boolean, default=True)
    features_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subscription_customer_status", "customer_id", "status"), UniqueConstraint("provider_subscription_id", name="uq_subscription_provider_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    plan_code: Mapped[str] = mapped_column(String(40), nullable=False)
    billing_interval: Mapped[str] = mapped_column(String(20), default="monthly")
    status: Mapped[str] = mapped_column(String(30), default="trialing")
    provider: Mapped[str] = mapped_column(String(30), default="internal")
    provider_customer_id: Mapped[str] = mapped_column(String(180), default="")
    provider_subscription_id: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    stripe_last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReferralCode(Base):
    __tablename__ = "referral_codes"
    __table_args__ = (UniqueConstraint("code", name="uq_referral_code"), Index("ix_referral_code_customer", "customer_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (UniqueConstraint("referred_customer_id", name="uq_referred_customer"), Index("ix_referral_referrer_status", "referrer_customer_id", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referral_code: Mapped[str] = mapped_column(String(40), nullable=False)
    referrer_customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    referred_customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReferralCommission(Base):
    __tablename__ = "referral_commissions"
    __table_args__ = (UniqueConstraint("subscription_id", "referral_id", "provider_reference", name="uq_referral_commission_invoice"), Index("ix_referral_commission_referrer_status", "referral_customer_id", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referral_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    referral_customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    referred_customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    subscription_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    gross_revenue: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    commission_pct: Mapped[float] = mapped_column(Float, default=0.0)
    commission_amount: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    provider_reference: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    eligible_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RevenueLedger(Base):
    __tablename__ = "revenue_ledger"
    __table_args__ = (UniqueConstraint("provider", "provider_reference", name="uq_revenue_provider_reference"), Index("ix_revenue_created", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    subscription_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(30), default="internal")
    provider_reference: Mapped[str] = mapped_column(String(180), nullable=False)
    gross_amount: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    refunds: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    net_amount: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CostLedger(Base):
    __tablename__ = "cost_ledger"
    __table_args__ = (Index("ix_cost_created_category", "created_at", "category"), Index("ix_cost_customer", "customer_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(60), default="")
    amount: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    reference: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SmartTrade(Base):
    __tablename__ = "smart_trades"
    __table_args__ = (
        ForeignKeyConstraint(["trading_account_id", "customer_id"], ["trading_accounts.id", "trading_accounts.customer_id"], name="fk_smart_trade_account_customer"),
        Index("ix_smart_trade_customer_status", "customer_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trading_account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(50), default="")
    symbol: Mapped[str] = mapped_column(String(80))
    side: Mapped[str] = mapped_column(String(10))
    entry_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    quantity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    stop_loss_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    take_profit_1: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    take_profit_2: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    take_profit_3: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    trailing_stop_pct: Mapped[float] = mapped_column(Float, default=0.0)
    breakeven_at_r: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="PAPER")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DcaBot(Base):
    __tablename__ = "dca_bots"
    __table_args__ = (
        ForeignKeyConstraint(["trading_account_id", "customer_id"], ["trading_accounts.id", "trading_accounts.customer_id"], name="fk_dca_bot_account_customer"),
        Index("ix_dca_bot_customer_status", "customer_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trading_account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(50), default="")
    symbol: Mapped[str] = mapped_column(String(80))
    side: Mapped[str] = mapped_column(String(10), default="LONG")
    initial_quote: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    safety_order_quote: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    max_safety_orders: Mapped[int] = mapped_column(Integer, default=3)
    deviation_pct: Mapped[float] = mapped_column(Float, default=1.0)
    volume_scale: Mapped[float] = mapped_column(Float, default=1.5)
    step_scale: Mapped[float] = mapped_column(Float, default=1.25)
    take_profit_pct: Mapped[float] = mapped_column(Float, default=2.0)
    stop_loss_pct: Mapped[float] = mapped_column(Float, default=5.0)
    trailing_take_profit_pct: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="STOPPED")
    mode: Mapped[str] = mapped_column(String(20), default="PAPER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GridBot(Base):
    __tablename__ = "grid_bots"
    __table_args__ = (
        ForeignKeyConstraint(["trading_account_id", "customer_id"], ["trading_accounts.id", "trading_accounts.customer_id"], name="fk_grid_bot_account_customer"),
        Index("ix_grid_bot_customer_status", "customer_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trading_account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(50), default="")
    symbol: Mapped[str] = mapped_column(String(80))
    grid_type: Mapped[str] = mapped_column(String(20), default="NEUTRAL")
    lower_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    upper_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    levels: Mapped[int] = mapped_column(Integer, default=20)
    arithmetic: Mapped[bool] = mapped_column(Boolean, default=False)
    quote_per_grid: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    take_profit_pct: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss_pct: Mapped[float] = mapped_column(Float, default=0.0)
    trailing_stop_pct: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="STOPPED")
    mode: Mapped[str] = mapped_column(String(20), default="PAPER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AdaptiveTradingBot(Base):
    __tablename__ = "adaptive_trading_bots"
    __table_args__ = (
        Index("ix_adaptive_bot_customer_status", "customer_id", "status"),
        UniqueConstraint("customer_id", "name", name="uq_adaptive_bot_customer_name"),
        ForeignKeyConstraint(["trading_account_id", "customer_id"], ["trading_accounts.id", "trading_accounts.customer_id"], name="fk_adaptive_bot_account_customer"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trading_account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), default="Atlas Adaptive AI")
    asset: Mapped[str] = mapped_column(String(20), default="crypto")
    symbol: Mapped[str] = mapped_column(String(80), default="BTC/USDT:USDT")
    exchange: Mapped[str] = mapped_column(String(50), default="binance")
    timeframe: Mapped[str] = mapped_column(String(20), default="1h")
    days: Mapped[int] = mapped_column(Integer, default=365)
    risk_fraction: Mapped[float] = mapped_column(Float, default=0.005)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=900)
    strategy_candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="STOPPED")
    mode: Mapped[str] = mapped_column(String(20), default="PAPER")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_decision: Mapped[str] = mapped_column(String(30), default="NONE")
    last_stage: Mapped[str] = mapped_column(String(60), default="")
    last_model_version: Mapped[str] = mapped_column(String(128), default="")
    active_strategy: Mapped[str] = mapped_column(String(40), default="")
    active_regime: Mapped[str] = mapped_column(String(40), default="")
    strategy_last_switched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    strategy_switch_count: Mapped[int] = mapped_column(Integer, default=0)
    strategy_selection_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (UniqueConstraint("customer_id", "name", name="uq_webhook_customer_name"), Index("ix_webhook_customer_status", "customer_id", "status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), default="TradingView")
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("endpoint_id", "event_id", name="uq_webhook_endpoint_event"), Index("ix_webhook_event_endpoint_created", "endpoint_id", "created_at"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StripeWebhookEvent(Base):
    __tablename__ = "stripe_webhook_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_stripe_webhook_event_id"),
        Index("ix_stripe_webhook_event_created", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(180), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    stripe_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExchangeConnector(Base):
    __tablename__ = "exchange_connectors"
    __table_args__ = (UniqueConstraint("name", name="uq_exchange_connector_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    market_types: Mapped[str] = mapped_column(String(120), default="spot")
    capabilities_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CustomerBinanceAccount(Base):
    __tablename__ = "customer_binance_accounts"
    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_customer_binance_account_customer"),
        UniqueConstraint("subaccount_id", name="uq_customer_binance_account_subaccount"),
        Index("ix_customer_binance_account_status", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    subaccount_id: Mapped[str] = mapped_column(String(120), nullable=False)
    api_key: Mapped[str] = mapped_column(EncryptedText, default="")
    secret_ref: Mapped[str] = mapped_column(String(255), default="")
    market_type: Mapped[str] = mapped_column(String(30), default="spot")
    can_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    margin_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    futures_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    universal_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_withdrawals: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomerDerivAccount(Base):
    __tablename__ = "customer_deriv_accounts"
    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_customer_deriv_account_customer"),
        UniqueConstraint("account_id", name="uq_customer_deriv_account_account_id"),
        Index("ix_customer_deriv_account_status", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    app_id: Mapped[int] = mapped_column(Integer, nullable=False)
    api_token: Mapped[str] = mapped_column(EncryptedText, default="")
    can_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    scope_status: Mapped[str] = mapped_column(String(60), default="UNVERIFIED")
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomerOandaAccount(Base):
    __tablename__ = "customer_oanda_accounts"
    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_customer_oanda_account_customer"),
        UniqueConstraint("account_id", name="uq_customer_oanda_account_account_id"),
        Index("ix_customer_oanda_account_status", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    api_token: Mapped[str] = mapped_column(EncryptedText, default="")
    practice: Mapped[bool] = mapped_column(Boolean, default=True)
    can_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    scope_status: Mapped[str] = mapped_column(String(60), default="UNVERIFIED")
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomerAlert(Base):
    __tablename__ = "customer_alerts"
    __table_args__ = (Index("ix_customer_alert_customer_status", "customer_id", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(String(40), default="PRICE")
    symbol: Mapped[str] = mapped_column(String(80), default="")
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    condition: Mapped[str] = mapped_column(String(20), default="ABOVE")
    channel: Mapped[str] = mapped_column(String(20), default="IN_APP")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    message: Mapped[str] = mapped_column(Text, default="")
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StrategyCandidate(Base):
    __tablename__ = "strategy_candidates"
    __table_args__ = (Index("ix_strategy_candidate_customer_status", "customer_id", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), default="Atlas Candidate")
    asset: Mapped[str] = mapped_column(String(20), default="crypto")
    symbol: Mapped[str] = mapped_column(String(80), default="BTC/USDT:USDT")
    exchange: Mapped[str] = mapped_column(String(50), default="binance")
    timeframe: Mapped[str] = mapped_column(String(20), default="1h")
    spec_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    backtest_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    oos_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    live_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TradeExecutor(Base):
    __tablename__ = "trade_executors"
    __table_args__ = (
        ForeignKeyConstraint(["trading_account_id", "customer_id"], ["trading_accounts.id", "trading_accounts.customer_id"], name="fk_executor_account_customer"),
        Index("ix_trade_executor_customer_status", "customer_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trading_account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    bot_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    asset: Mapped[str] = mapped_column(String(20), default="crypto")
    exchange: Mapped[str] = mapped_column(String(50), default="binance")
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(20), default="1h")
    config_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    executed_quantity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    target_quantity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="ARMED")
    mode: Mapped[str] = mapped_column(String(20), default="PAPER")
    live_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StrategyDraft(Base):
    __tablename__ = "strategy_drafts"
    __table_args__ = (Index("ix_strategy_draft_customer_created", "customer_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), default="Atlas AI Strategy")
    prompt: Mapped[str] = mapped_column(Text, default="")
    strategy_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StrategyCandidateRun(Base):
    """One immutable record per validate() attempt on a StrategyCandidate.

    Added because validate_strategy_candidate() previously overwrote
    StrategyCandidate.backtest_json/oos_json in place on every call, so re-validating
    a candidate (after a market/timeframe tweak, or just retrying) silently discarded
    the prior attempt with no way to compare "this version vs last version." This table
    is the experiment-tracking history that was missing; the candidate row itself keeps
    the latest values for backward-compatible reads.
    """
    __tablename__ = "strategy_candidate_runs"
    __table_args__ = (Index("ix_strategy_candidate_run_candidate", "candidate_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    backtest_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    oos_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    gate_json: Mapped[str] = mapped_column(Text, default="{}")
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelExperiment(Base):
    """One record per adaptive-model retrain attempt (promoted or rejected).

    Previously ensure_adaptive_model() only ever wrote the current champion's
    metadata file in place (model_path + ".adaptive.json"), so there was no history of
    past challengers, past champions, or the feature-drift readings that triggered a
    given retrain -- only "what's deployed right now" was ever visible. This table is
    the experiment registry that was missing, independent of the on-disk champion file
    (which remains the source of truth for what's actually loaded and serving).
    """
    __tablename__ = "model_experiments"
    __table_args__ = (Index("ix_model_experiment_path_created", "model_path", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_path: Mapped[str] = mapped_column(String(400), nullable=False, index=True)
    asset: Mapped[str] = mapped_column(String(20), default="crypto")
    status: Mapped[str] = mapped_column(String(30), nullable=False)  # CHAMPION_PROMOTED / CHALLENGER_REJECTED / CHAMPION_FRESH
    model_sha256: Mapped[str] = mapped_column(String(128), default="")
    gate_json: Mapped[str] = mapped_column(Text, default="{}")
    wfo_json: Mapped[str] = mapped_column(Text, default="{}")
    feature_drift_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StrategyOutcome(Base):
    """Observed trading outcome used by the adaptive strategy router.

    This table is separate from research/backtest results: only observed executions
    are stored here. It lets the router incorporate real slippage/fee-adjusted outcomes
    without contaminating the historical OOS research datasets.
    """
    __tablename__ = "strategy_outcomes"
    __table_args__ = (
        UniqueConstraint("trade_id", "sequence", name="uq_strategy_outcome_trade_sequence"),
        Index("ix_strategy_outcome_customer_strategy_created", "customer_id", "strategy", "created_at"),
        Index("ix_strategy_outcome_symbol_regime_created", "symbol", "regime", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    closing_trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    bot_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    strategy: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    regime: Mapped[str] = mapped_column(String(40), nullable=False, default="UNKNOWN", index=True)
    asset: Mapped[str] = mapped_column(String(20), nullable=False, default="crypto", index=True)
    symbol: Mapped[str] = mapped_column(String(80), default="", index=True)
    timeframe: Mapped[str] = mapped_column(String(20), default="")
    side: Mapped[str] = mapped_column(String(10), default="")
    realized_pnl: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    fee: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    return_bps: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    net_return_bps: Mapped[float] = mapped_column(Float, default=0.0)
    mode: Mapped[str] = mapped_column(String(20), default="")
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    model_version: Mapped[str] = mapped_column(String(128), default="")
    metadata_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TradeLearningEpisode(Base):
    """Immutable-at-entry, mutable-at-outcome memory for one adaptive position lifecycle.

    An episode is anchored to the trade that opened the position. Additional partial fills
    can update the same episode. This is deliberately post-trade memory: future prices and
    counterfactuals are never fed back into the live decision snapshot.
    """
    __tablename__ = "trade_learning_episodes"
    __table_args__ = (
        UniqueConstraint("entry_trade_id", name="uq_trade_learning_episode_entry_trade"),
        Index("ix_trade_learning_episode_customer_exit", "customer_id", "exit_at"),
        Index("ix_trade_learning_episode_status_replay", "status", "replay_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_trade_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    closing_trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    bot_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    asset: Mapped[str] = mapped_column(String(20), default="crypto", index=True)
    exchange: Mapped[str] = mapped_column(String(50), default="", index=True)
    symbol: Mapped[str] = mapped_column(String(80), default="", index=True)
    timeframe: Mapped[str] = mapped_column(String(20), default="")
    side: Mapped[str] = mapped_column(String(10), default="")
    strategy: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    regime: Mapped[str] = mapped_column(String(40), default="UNKNOWN", index=True)
    model_version: Mapped[str] = mapped_column(String(128), default="")
    entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_quantity: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    entry_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    exit_price: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    gross_pnl: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    total_fees: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    net_pnl: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    return_bps: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    replay_status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    replay_version: Mapped[str] = mapped_column(String(80), default="")
    replay_error: Mapped[str] = mapped_column(Text, default="")
    bars_held: Mapped[int] = mapped_column(Integer, default=0)
    mfe_bps: Mapped[float] = mapped_column(Float, default=0.0)
    mae_bps: Mapped[float] = mapped_column(Float, default=0.0)
    decision_snapshot_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    market_flow_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    learning_memory_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TradeReplayResult(Base):
    """Counterfactual strategy replay for a completed trade-learning episode."""
    __tablename__ = "trade_replay_results"
    __table_args__ = (
        UniqueConstraint("episode_id", "strategy", name="uq_trade_replay_episode_strategy"),
        Index("ix_trade_replay_episode", "episode_id"),
        Index("ix_trade_replay_strategy_created", "strategy", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entry_signal: Mapped[float] = mapped_column(Float, default=0.0)
    entry_side: Mapped[str] = mapped_column(String(10), default="flat")
    entry_decision_return_bps: Mapped[float] = mapped_column(Float, default=0.0)
    policy_window_return_bps: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[str] = mapped_column(String(20), default="LOW")
    comparison_scope: Mapped[str] = mapped_column(String(120), default="")
    metadata_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ResearchRun(Base):
    """One record per symbol per daily research cycle.

    daily_research.py's own generated brief has always told the next run to "compare
    against this run for regime and performance drift" -- but the run's output was never
    persisted anywhere (the autonomous loop only logged {status, symbols} to the audit
    trail), so there was nothing for the next run to compare against. This table makes
    that comparison possible; `regime_drift_json` on each new row stores what actually
    changed vs. the immediately preceding run for that symbol.
    """
    __tablename__ = "research_runs"
    __table_args__ = (Index("ix_research_run_symbol_created", "symbol", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    regime_assessment: Mapped[str] = mapped_column(String(60), default="")
    top_strategy: Mapped[str] = mapped_column(String(40), default="")
    sharpe: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    total_return: Mapped[float] = mapped_column(Float, default=0.0)
    regime_drift_json: Mapped[str] = mapped_column(Text, default="{}")
    research_json: Mapped[str] = mapped_column(Text, default="{}")
    review_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FundingTransaction(Base):
    __tablename__ = "funding_transactions"
    __table_args__ = (
        UniqueConstraint("provider", "provider_reference", name="uq_funding_provider_reference"),
        ForeignKeyConstraint(["wallet_id", "customer_id"], ["wallets.id", "wallets.customer_id"], name="fk_funding_wallet_customer"),
        Index("ix_funding_customer_status", "customer_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    wallet_id: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), default="")
    provider_reference: Mapped[str] = mapped_column(String(180), nullable=False)
    amount: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    currency: Mapped[str] = mapped_column(String(20), default="USD")
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    metadata_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class TronDepositCursor(Base):
    __tablename__ = "tron_deposit_cursors"
    __table_args__ = (UniqueConstraint("wallet_id", name="uq_tron_deposit_cursor_wallet"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    last_block_timestamp: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class TronSweep(Base):
    __tablename__ = "tron_sweeps"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_tron_sweep_idempotency"),
        Index("ix_tron_sweep_wallet_status", "wallet_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_address: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    treasury_address: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    amount_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(20), default="USDT")
    contract_address: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="READY_FOR_SIGNER")
    transaction_id: Mapped[str] = mapped_column(String(128), default="")
    detail_json: Mapped[str] = mapped_column(EncryptedText, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class ArbitrageOpportunity(Base):
    __tablename__ = "arbitrage_opportunities"
    __table_args__ = (Index("ix_arb_customer_created", "customer_id", "created_at"), Index("ix_arb_status", "status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    trading_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    exchange: Mapped[str] = mapped_column(String(50), default="binance")
    path_json: Mapped[str] = mapped_column(Text, default="[]")
    start_quote: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    end_quote: Mapped[float] = mapped_column(FinancialNumeric, default=0.0)
    gross_edge_pct: Mapped[float] = mapped_column(Float, default=0.0)
    fees_pct: Mapped[float] = mapped_column(Float, default=0.0)
    slippage_buffer_pct: Mapped[float] = mapped_column(Float, default=0.0)
    safety_buffer_pct: Mapped[float] = mapped_column(Float, default=0.0)
    net_edge_pct: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="PAPER_CANDIDATE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
