from __future__ import annotations
from typing import Any
from .forex_oanda import OandaBroker, OandaConfig, OandaError


def build_customer_oanda_broker(account: Any, *, timeout_seconds: float = 10.0) -> OandaBroker:
    if account is None:
        raise OandaError("Customer OANDA account mapping not found")
    if str(getattr(account, "status", "")).upper() != "VERIFIED":
        raise OandaError("Customer OANDA account is not verified")
    if not bool(getattr(account, "practice", True)):
        raise OandaError("OANDA is demo/backtesting-only in AtlasRisk; live OANDA accounts are not supported")
    if str(getattr(account, "scope_status", "")) != "OANDA_PROVIDER_TOKEN_ACCESS_CONFIRMED":
        raise OandaError("Customer OANDA credential capability has not been verified")
    if not bool(getattr(account, "can_trade", False)):
        raise OandaError("Customer OANDA account is not trade-enabled")
    account_id = str(getattr(account, "account_id", "") or "").strip()
    token = str(getattr(account, "api_token", "") or "").strip()
    if not account_id or not token:
        raise OandaError("Customer OANDA credentials are incomplete")
    broker = OandaBroker(OandaConfig(account_id, token, True, timeout_seconds))
    try:
        summary = broker.account().get("account") or {}
        returned_id = str(summary.get("id") or "").strip()
        if returned_id != account_id:
            raise OandaError("OANDA account identity verification failed")
    except Exception:
        broker.close()
        raise
    return broker
