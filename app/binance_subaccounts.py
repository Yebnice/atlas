from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class BinanceSubAccountError(RuntimeError):
    pass


@dataclass(frozen=True)
class BinanceSubAccountProvision:
    customer_id: int
    tag: str
    subaccount_id: str
    api_key: str = ""
    secret_key: str = ""
    can_trade: bool = False
    margin_trade: bool = False
    futures_trade: bool = False
    universal_transfer: bool = False
    enable_withdrawals: bool = False

    @property
    def trading_only(self) -> bool:
        return self.can_trade and not self.universal_transfer


def validate_provision_response(customer_id: int, tag: str, payload: Mapping[str, Any]) -> BinanceSubAccountProvision:
    """Normalize Binance Broker sub-account creation/API-key responses.

    The secret is returned by Binance only at API-key creation time. Atlas must
    immediately hand it to Secret Manager and never persist it in this model or
    the application database.
    """
    sub_id = str(payload.get("subaccountId") or payload.get("subAccountId") or "").strip()
    if not sub_id:
        raise BinanceSubAccountError("Binance response did not contain a sub-account id")
    api_key = str(payload.get("apiKey") or payload.get("apikey") or "")
    secret_key = str(payload.get("secretKey") or "")
    can_trade = bool(payload.get("canTrade", False))
    margin = bool(payload.get("marginTrade", False))
    futures = bool(payload.get("futuresTrade", False))
    universal = bool(payload.get("canUniversalTransfer", payload.get("universalTransfer", False)))
    withdrawals = bool(payload.get("enableWithdrawals", False))
    if not can_trade:
        raise BinanceSubAccountError("Binance sub-account API key is not trade-enabled")
    if universal:
        raise BinanceSubAccountError("Atlas Binance customer key must not have universal-transfer permission")
    if withdrawals:
        raise BinanceSubAccountError("Atlas Binance customer key must have withdrawals disabled")
    return BinanceSubAccountProvision(
        customer_id=customer_id,
        tag=tag,
        subaccount_id=sub_id,
        api_key=api_key,
        secret_key=secret_key,
        can_trade=can_trade,
        margin_trade=margin,
        futures_trade=futures,
        universal_transfer=universal,
        enable_withdrawals=withdrawals,
    )


def build_provision_plan(customer_id: int, tag: str) -> dict[str, Any]:
    """Return the least-privilege Binance provisioning plan.

    Creation of a Binance Broker sub-account/API key remains an explicit
    operator action because Binance applies eligibility/KYC restrictions.
    """
    if customer_id <= 0:
        raise BinanceSubAccountError("customer_id must be positive")
    safe_tag = str(tag).strip()
    if not safe_tag or len(safe_tag) > 31:
        raise BinanceSubAccountError("Binance sub-account tag must be 1-31 characters")
    return {
        "customer_id": customer_id,
        "tag": safe_tag,
        "create_subaccount": {"tag": safe_tag},
        "create_api_key": {"canTrade": True, "marginTrade": False, "futuresTrade": False, "enableWithdrawals": False, "universalTransfer": False},
        "required_permissions": {"trade": True, "marginTrade": False, "futuresTrade": False, "enableWithdrawals": False, "universalTransfer": False},
        "secret_storage": "google-secret-manager",
        "database_secret_storage": False,
    }
