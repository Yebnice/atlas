from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .broker import Broker, BrokerConfig


class CustomerBinanceExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CustomerBinanceCredentials:
    api_key: str
    api_secret: str
    secret_ref: str


def resolve_secret(secret_ref: str, fetcher: Callable[[str], str] | None = None) -> str:
    """Resolve a customer Binance secret without persisting it in Atlas DB.

    Production supplies a Secret Manager-backed fetcher. Tests can inject a
    deterministic fetcher; Atlas never falls back to the platform Binance key.
    """
    ref = str(secret_ref or "").strip()
    if not ref:
        raise CustomerBinanceExecutionError("Customer Binance secret reference is missing")
    if fetcher is None:
        try:
            from google.cloud import secretmanager  # type: ignore
        except Exception as exc:
            raise CustomerBinanceExecutionError("Google Secret Manager client is unavailable") from exc
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(name=ref)
        secret = response.payload.data.decode("utf-8").strip()
    else:
        secret = str(fetcher(ref) or "").strip()
    if not secret:
        raise CustomerBinanceExecutionError("Customer Binance secret resolved to an empty value")
    return secret


def build_customer_binance_broker(
    account: Any,
    *,
    secret_fetcher: Callable[[str], str] | None = None,
    timeout_ms: int = 10_000,
    sandbox: bool = False,
) -> Broker:
    """Build a broker strictly from a verified customer Binance account."""
    if account is None:
        raise CustomerBinanceExecutionError("Customer Binance account mapping not found")
    if str(getattr(account, "status", "")).upper() != "VERIFIED":
        raise CustomerBinanceExecutionError("Customer Binance account is not verified")
    if not bool(getattr(account, "can_trade", False)):
        raise CustomerBinanceExecutionError("Customer Binance account is not trade-enabled")
    if bool(getattr(account, "universal_transfer", False)):
        raise CustomerBinanceExecutionError("Customer Binance account has forbidden universal-transfer permission")
    if bool(getattr(account, "enable_withdrawals", False)):
        raise CustomerBinanceExecutionError("Customer Binance account has withdrawals enabled")
    api_key = str(getattr(account, "api_key", "") or "").strip()
    secret_ref = str(getattr(account, "secret_ref", "") or "").strip()
    if not api_key or not secret_ref:
        raise CustomerBinanceExecutionError("Customer Binance credentials are incomplete")
    secret = resolve_secret(secret_ref, secret_fetcher)
    return Broker.get(BrokerConfig(
        exchange_id="binance",
        api_key=api_key,
        api_secret=secret,
        password="",
        sandbox=sandbox,
        market_type=str(getattr(account, "market_type", "spot") or "spot"),
        timeout_ms=timeout_ms,
    ))
