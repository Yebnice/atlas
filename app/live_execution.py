from __future__ import annotations

from sqlalchemy import select
from datetime import datetime, timezone

from .config import settings
from .db import AppState, TradingAccount, CustomerProfile, CustomerBinanceAccount, Subscription, Plan


class LiveExecutionBlocked(RuntimeError):
    pass


async def assert_live_system_enabled(
    db,
    *,
    asset: str,
    customer_id: int | None,
    exchange: str,
    side: str,
    quantity: float,
    reduce_only: bool = False,
) -> None:
    """Final deny-by-default server-side gate immediately before a live order call."""
    state = (await db.execute(select(AppState).where(AppState.id == 1).with_for_update())).scalar_one_or_none()
    if not state:
        raise LiveExecutionBlocked("Live execution state is unavailable")
    if state.kill_switch or not state.live_enabled:
        raise LiveExecutionBlocked("Live trading is halted by the platform risk state")

    normalized_asset = str(asset or "crypto").lower()
    normalized_exchange = str(exchange or "").lower()
    if normalized_asset in {"forex", "commodity"}:
        raise LiveExecutionBlocked("OANDA Forex/commodity execution is demo-only in AtlasRisk")
    if not settings.live_trading_enabled or settings.paper_trading or settings.broker_sandbox:
        raise LiveExecutionBlocked("Live execution is disabled by platform configuration")
    if quantity <= 0 or side not in {"buy", "sell"}:
        raise LiveExecutionBlocked("Invalid live order parameters")

    if customer_id is None:
        if not settings.exchange_api_key or not settings.exchange_api_secret:
            raise LiveExecutionBlocked("Platform exchange credentials are not configured")
        return

    if not settings.customer_live_trading_enabled:
        raise LiveExecutionBlocked("Customer live trading is not enabled")

    profile = (await db.execute(select(CustomerProfile).where(CustomerProfile.id == customer_id).with_for_update())).scalar_one_or_none()
    if not profile or str(profile.status).upper() != "ACTIVE":
        raise LiveExecutionBlocked("Customer account is not active")

    account = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == customer_id).with_for_update())).scalar_one_or_none()
    if not account:
        raise LiveExecutionBlocked("Customer trading account is unavailable")
    account_status = str(account.status).upper()
    if account_status != "ACTIVE" and not (account_status == "HALTED" and reduce_only):
        raise LiveExecutionBlocked("Customer trading account is not active")

    sub = (await db.execute(
        select(Subscription).where(
            Subscription.customer_id == customer_id,
            Subscription.status.in_(["trialing", "active", "past_due"]),
        ).order_by(Subscription.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if not sub:
        raise LiveExecutionBlocked("Customer live-trading subscription is not active")
    if str(sub.status).lower() == "trialing" and getattr(sub, "trial_end", None) is not None:
        trial_end = sub.trial_end
        if trial_end.tzinfo is None:
            trial_end = trial_end.replace(tzinfo=timezone.utc)
        if trial_end <= datetime.now(timezone.utc):
            raise LiveExecutionBlocked("Customer trial entitlement has expired")
    plan = (await db.execute(select(Plan).where(Plan.code == sub.plan_code))).scalar_one_or_none()
    if not plan or not bool(plan.active) or not bool(plan.live_trading):
        raise LiveExecutionBlocked("Customer plan does not permit live trading")

    if normalized_asset == "crypto":
        if normalized_exchange != "binance":
            raise LiveExecutionBlocked("Customer live crypto trading requires the verified Binance isolation path")
        customer_binance = (await db.execute(
            select(CustomerBinanceAccount).where(CustomerBinanceAccount.customer_id == customer_id).with_for_update()
        )).scalar_one_or_none()
        if not customer_binance:
            raise LiveExecutionBlocked("Verified customer Binance account is missing")
        if str(customer_binance.status).upper() != "VERIFIED" or not bool(customer_binance.can_trade):
            raise LiveExecutionBlocked("Customer Binance account is not verified for trading")
        if bool(customer_binance.enable_withdrawals) or bool(customer_binance.universal_transfer):
            raise LiveExecutionBlocked("Customer Binance key has forbidden transfer/withdrawal permissions")
