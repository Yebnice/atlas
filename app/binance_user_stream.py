from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import json


class BinanceUserStreamError(RuntimeError):
    pass


@dataclass(frozen=True)
class OrderUpdate:
    symbol: str
    order_id: str
    client_order_id: str
    status: str
    execution_type: str
    side: str
    original_qty: float
    executed_qty: float
    last_fill_qty: float
    last_fill_price: float
    cumulative_quote_qty: float
    event_time_ms: int

    @property
    def terminal(self) -> bool:
        return self.status in {"FILLED", "CANCELED", "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH"}


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_order_update(message: str | bytes | Mapping[str, Any]) -> OrderUpdate | None:
    """Normalize Binance Spot user-data order updates.

    Supports the current authenticated User Data Stream wrapper and the legacy
    executionReport shape so recovery remains compatible across transport modes.
    """
    if isinstance(message, (str, bytes)):
        try:
            payload = json.loads(message)
        except json.JSONDecodeError as exc:
            raise BinanceUserStreamError("Invalid Binance user-stream JSON") from exc
    else:
        payload = dict(message)

    # Current WebSocket API may wrap event data; tolerate common wrapper keys.
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    event = str(data.get("e") or data.get("eventType") or data.get("type") or "")
    if event not in {"executionReport", "ORDER_TRADE_UPDATE", "orderReport", "ORDER_UPDATE", "ORDER_TERMINAL"}:
        return None

    order = data.get("o") if isinstance(data.get("o"), Mapping) else data
    symbol = str(order.get("s") or order.get("symbol") or "")
    order_id = str(order.get("i") or order.get("orderId") or "")
    client_id = str(order.get("c") or order.get("clientOrderId") or "")
    status = str(order.get("X") or order.get("status") or "").upper()
    execution_type = str(order.get("x") or order.get("executionType") or "").upper()
    side = str(order.get("S") or order.get("side") or "").upper()
    if not symbol or not order_id or not client_id:
        raise BinanceUserStreamError("Binance order update missing identity fields")

    return OrderUpdate(
        symbol=symbol,
        order_id=order_id,
        client_order_id=client_id,
        status=status,
        execution_type=execution_type,
        side=side,
        original_qty=_float(order.get("q") or order.get("origQty")),
        executed_qty=_float(order.get("z") or order.get("executedQty")),
        last_fill_qty=_float(order.get("l") or order.get("lastExecutedQty")),
        last_fill_price=_float(order.get("L") or order.get("lastExecutedPrice")),
        cumulative_quote_qty=_float(order.get("Z") or order.get("cummulativeQuoteQty")),
        event_time_ms=int(data.get("E") or order.get("T") or order.get("updateTime") or 0),
    )


def build_signed_subscription(api_key: str, timestamp_ms: int, signature: str, recv_window: int = 5000) -> dict[str, Any]:
    """Build the documented signed user-data subscription request.

    Signing is intentionally injected so Atlas can use its configured Binance
    signing implementation without storing or exposing credentials here.
    """
    if not api_key or not signature:
        raise BinanceUserStreamError("API key and signature are required")
    return {
        "id": f"atlas-user-stream-{timestamp_ms}",
        "method": "userDataStream.subscribe.signature",
        "params": {
            "apiKey": api_key,
            "timestamp": timestamp_ms,
            "recvWindow": recv_window,
            "signature": signature,
        },
    }
