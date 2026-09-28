from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


class BinanceArbRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class LegFill:
    symbol: str
    side: str
    requested: float
    filled: float
    average: float
    status: str
    order_id: str = ""
    client_order_id: str = ""
    fee_quote: float = 0.0

    @property
    def complete(self) -> bool:
        return self.filled > 0 and self.filled + 1e-12 >= self.requested and self.status.lower() in {"closed", "filled"}


def _d(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def validate_symbol_filters(symbol_info: Mapping[str, Any], side: str, quantity: float, price: float, notional: float) -> None:
    """Validate common Binance spot filters before a live arbitrage order."""
    filters = {str(x.get("filterType")): x for x in (symbol_info.get("filters") or [])}
    p = _d(price)
    q = _d(quantity)
    n = _d(notional)

    pf = filters.get("PRICE_FILTER")
    if pf:
        min_price, max_price, tick = _d(pf.get("minPrice")), _d(pf.get("maxPrice")), _d(pf.get("tickSize"))
        if min_price and p < min_price: raise BinanceArbRecoveryError("PRICE_FILTER: price below minimum")
        if max_price and p > max_price: raise BinanceArbRecoveryError("PRICE_FILTER: price above maximum")
        if tick and (p % tick != 0): raise BinanceArbRecoveryError("PRICE_FILTER: price not aligned to tick size")

    lf = filters.get("LOT_SIZE")
    if lf:
        min_q, max_q, step = _d(lf.get("minQty")), _d(lf.get("maxQty")), _d(lf.get("stepSize"))
        if min_q and q < min_q: raise BinanceArbRecoveryError("LOT_SIZE: quantity below minimum")
        if max_q and q > max_q: raise BinanceArbRecoveryError("LOT_SIZE: quantity above maximum")
        if step and (q % step != 0): raise BinanceArbRecoveryError("LOT_SIZE: quantity not aligned to step size")

    nf = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
    if nf:
        minimum = _d(nf.get("minNotional"))
        if minimum and n < minimum: raise BinanceArbRecoveryError("MIN_NOTIONAL: order notional below minimum")


class BinanceArbRecovery:
    """Resolve an ambiguous leg and prevent the next leg from being submitted until state is known."""
    def __init__(self, broker: Any):
        self.broker = broker

    def resolve(self, symbol: str, order_id: str | None = None, client_order_id: str | None = None) -> dict[str, Any]:
        if order_id:
            try:
                return self.broker.order_status(symbol, order_id)
            except Exception:
                pass
        if client_order_id and hasattr(self.broker, "find_order_by_client_id"):
            result = self.broker.find_order_by_client_id(symbol, client_order_id)
            if result:
                return result
        raise BinanceArbRecoveryError("Binance arbitrage leg remains UNKNOWN; manual/recovery reconciliation required")

    @staticmethod
    def can_continue(receipt: Mapping[str, Any], requested: float) -> bool:
        status = str(receipt.get("status") or "").lower()
        filled = float(receipt.get("filled") or receipt.get("executedQty") or 0)
        return status in {"closed", "filled"} and filled + 1e-12 >= requested

    @staticmethod
    def exposure_after_partial(receipt: Mapping[str, Any], side: str, requested: float) -> dict[str, float]:
        filled = float(receipt.get("filled") or receipt.get("executedQty") or 0)
        remaining = max(0.0, requested - filled)
        return {"filled": filled, "remaining": remaining, "unhedged_quantity": filled if filled < requested else 0.0}


@dataclass(frozen=True)
class Exposure:
    asset: str
    quantity: float
    reason: str

    @property
    def needs_flatten(self) -> bool:
        return abs(self.quantity) > 1e-12


def partial_leg_exposure(receipt: Mapping[str, Any], side: str, base_asset: str, requested: float) -> Exposure:
    """Return the base-asset exposure created by an incomplete leg.

    For a BUY, filled base is a positive exposure. For a SELL, filled base is a
    negative exposure. This is intentionally independent of the next triangle leg.
    """
    filled = float(receipt.get("filled") or receipt.get("executedQty") or 0)
    signed = filled if str(side).upper() == "BUY" else -filled
    return Exposure(base_asset.upper(), signed, "partial_arbitrage_leg")


def neutralization_side(exposure: Exposure) -> str:
    if not exposure.needs_flatten:
        raise BinanceArbRecoveryError("No exposure requires neutralization")
    return "SELL" if exposure.quantity > 0 else "BUY"
