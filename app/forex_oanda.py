from __future__ import annotations
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any
import httpx


class OandaError(RuntimeError):
    pass


@dataclass(frozen=True)
class OandaConfig:
    account_id: str
    token: str
    practice: bool = True
    timeout_seconds: float = 10.0

    def __post_init__(self):
        if not self.practice:
            raise OandaError("AtlasRisk OANDA adapter is permanently practice/demo-only; live OANDA is unsupported")

    @property
    def base_url(self) -> str:
        return "https://api-fxpractice.oanda.com"


class OandaUnknown(OandaError):
    pass


class OandaBroker:
    """Synchronous v20 OANDA adapter. Network calls are run in asyncio.to_thread by callers."""
    def __init__(self, config: OandaConfig):
        if not config.account_id or not config.token:
            raise OandaError("OANDA account ID and API token are required")
        self.config = config
        self.client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            headers={"Authorization": f"Bearer {config.token}", "Content-Type": "application/json"},
        )

    def close(self):
        self.client.close()

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            r = self.client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise OandaUnknown(str(e)) from e
        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = {"error": r.text[:500]}
            raise OandaError(f"OANDA HTTP {r.status_code}: {body}")
        return r.json()

    def account(self) -> dict[str, Any]:
        return self._request("GET", f"/v3/accounts/{self.config.account_id}")

    def pricing(self, instrument: str) -> dict[str, Any]:
        data = self._request("GET", f"/v3/accounts/{self.config.account_id}/pricing", params={"instruments": instrument})
        prices = data.get("prices") or []
        if not prices:
            raise OandaError(f"No OANDA price for {instrument}")
        return prices[0]

    def candles(self, instrument: str, granularity: str, count: int = 500) -> list[dict[str, Any]]:
        data = self._request(
            "GET", f"/v3/instruments/{instrument}/candles",
            params={"granularity": granularity, "count": min(count, 5000), "price": "M"},
        )
        return data.get("candles") or []

    @staticmethod
    def _decimal_price(obj: dict[str, Any], side: str) -> float:
        # OANDA pricing uses bid/ask arrays; first liquidity level is adequate for market quoting.
        key = "asks" if side == "buy" else "bids"
        levels = obj.get(key) or []
        if not levels:
            raise OandaError("OANDA returned no executable liquidity")
        return float(levels[0]["price"])

    def ticker(self, instrument: str) -> dict[str, Any]:
        p = self.pricing(instrument)
        bid = float((p.get("bids") or [{}])[0].get("price") or 0)
        ask = float((p.get("asks") or [{}])[0].get("price") or 0)
        return {"bid": bid, "ask": ask, "last": (bid + ask) / 2 if bid and ask else max(bid, ask), "timestamp": p.get("time")}

    def market_info(self, instrument: str) -> dict[str, Any]:
        data = self._request("GET", f"/v3/accounts/{self.config.account_id}/instruments", params={"instruments": instrument})
        rows = data.get("instruments") or []
        if not rows:
            raise OandaError(f"Unknown/non-tradeable OANDA instrument: {instrument}")
        return rows[0]

    def supports_protection(self, instrument: str) -> bool:
        info = self.market_info(instrument)
        return bool(info.get("name"))

    def normalize_amount(self, instrument: str, amount: float) -> float:
        info = self.market_info(instrument)
        precision = int(info.get("tradeUnitsPrecision") or 0)
        normalized = round(float(amount), precision)
        if precision == 0:
            return int(normalized)
        return normalized

    def normalize_price(self, instrument: str, price: float) -> float:
        info = self.market_info(instrument)
        precision = int(info.get("displayPrecision") or 5)
        return round(float(price), precision)

    def validate_order_units(self, instrument: str, units: float) -> float:
        info = self.market_info(instrument)
        normalized = self.normalize_amount(instrument, units)
        minimum = float(info.get("minimumTradeSize") or 0)
        maximum = info.get("maximumOrderUnits")
        if normalized <= 0:
            raise OandaError("OANDA order units round to zero")
        if minimum and normalized < minimum:
            raise OandaError("OANDA order size is below the instrument minimum")
        if maximum is not None and normalized > float(maximum):
            raise OandaError("OANDA order size exceeds the instrument maximum")
        return normalized

    def supports_feature(self, instrument: str, feature: str) -> bool:
        return feature in {"stopLoss", "takeProfit"} and self.supports_protection(instrument)

    @staticmethod
    def quote_age_seconds(timestamp: str | None) -> float | None:
        if not timestamp:
            return None
        try:
            value = timestamp.replace("Z", "+00:00")
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return None

    def validate_practice_quote(self, instrument: str, max_age_seconds: float = 3.0) -> dict[str, Any]:
        price = self.pricing(instrument)
        if not bool(price.get("tradeable")):
            raise OandaError(f"OANDA instrument is not tradeable: {instrument}")
        bids = price.get("bids") or []
        asks = price.get("asks") or []
        if not bids or not asks:
            raise OandaError("OANDA returned no executable bid/ask liquidity")
        bid = float(bids[0].get("price") or 0)
        ask = float(asks[0].get("price") or 0)
        if bid <= 0 or ask <= 0 or ask < bid:
            raise OandaError("OANDA returned an invalid bid/ask")
        age = self.quote_age_seconds(price.get("time"))
        if age is None or age > max_age_seconds:
            raise OandaError("OANDA practice quote is stale or has an invalid timestamp")
        info = self.market_info(instrument)
        return {"instrument": instrument, "tradeable": True, "bid": bid, "ask": ask,
                "spread": ask - bid, "timestamp": price.get("time"), "age_seconds": age,
                "trade_units_precision": int(info.get("tradeUnitsPrecision") or 0),
                "minimum_trade_size": float(info.get("minimumTradeSize") or 0),
                "maximum_order_units": float(info.get("maximumOrderUnits") or 0) if info.get("maximumOrderUnits") is not None else None}

    def pricing_stream_url(self) -> str:
        return ("https://stream-fxpractice.oanda.com" if self.config.practice
                else "https://stream-fxtrade.oanda.com") + f"/v3/accounts/{self.config.account_id}/pricing/stream"

    def market_order(self, instrument: str, side: str, units: float, client_order_id: str,
                     stop_loss_price: float | None = None, take_profit_price: float | None = None) -> dict[str, Any]:
        instrument = str(instrument).strip().upper()
        if side not in {"buy", "sell"}:
            raise OandaError("Invalid OANDA order side")
        units = self.validate_order_units(instrument, float(units))
        signed_units = units if side == "buy" else -units
        order: dict[str, Any] = {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(signed_units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "clientExtensions": {"id": client_order_id, "tag": "ai-trading"},
        }
        if stop_loss_price is not None:
            order["stopLossOnFill"] = {"price": f"{self.normalize_price(instrument, stop_loss_price):f}", "timeInForce": "GTC"}
        if take_profit_price is not None:
            order["takeProfitOnFill"] = {"price": f"{self.normalize_price(instrument, take_profit_price):f}", "timeInForce": "GTC"}
        try:
            data = self._request("POST", f"/v3/accounts/{self.config.account_id}/orders", json={"order": order})
        except OandaUnknown:
            raise
        create = data.get("orderCreateTransaction") or {}
        fill = data.get("orderFillTransaction") or {}
        cancel = data.get("orderCancelTransaction") or {}
        fill_units = abs(float(fill.get("units") or 0))
        fill_price = float(fill.get("price") or create.get("price") or 0)
        status = "closed" if fill_units > 0 else ("canceled" if cancel else "open")
        return {"id": str(create.get("id") or ""), "status": status, "filled": fill_units,
                "average": fill_price, "price": fill_price, "raw": data,
                "request_id": data.get("lastTransactionID") or create.get("requestID", "")}

    def order(self, order_id: str) -> dict[str, Any] | None:
        data = self._request("GET", f"/v3/accounts/{self.config.account_id}/orders/{order_id}")
        order = data.get("order") or {}
        fill = data.get("orderFillTransaction") or {}
        cancel = data.get("orderCancelTransaction") or {}
        filled = abs(float(fill.get("units") or order.get("filledUnits") or 0))
        price = float(fill.get("price") or order.get("averagePrice") or order.get("price") or 0)
        state = str(order.get("state") or "").upper()
        status = "closed" if state == "FILLED" or filled > 0 and state in {"FILLED", "TRIGGERED"} else (
            "canceled" if state in {"CANCELLED", "REJECTED"} or cancel else "open")
        return {"id": str(order.get("id") or order_id), "status": status, "filled": filled,
                "average": price, "price": price,
                "clientOrderId": str((order.get("clientExtensions") or {}).get("id") or "")}

    def resolve_unknown_order(self, client_order_id: str, known_transaction_id: str | None = None) -> dict[str, Any] | None:
        """Resolve an order after an ambiguous transport failure without resubmitting it.

        Resolution is intentionally read-only: direct clientOrderID lookup first, then
        incremental transaction history when a durable cursor is available.
        """
        if not client_order_id:
            raise OandaError("A client order ID is required to resolve an unknown order")
        order = self.find_order_by_client_id(client_order_id)
        if order is not None:
            return order
        if known_transaction_id:
            data = self.transactions_since(known_transaction_id)
            for tx in data.get("transactions") or []:
                ext = tx.get("clientExtensions") or {}
                if str(ext.get("id") or "") == client_order_id:
                    oid = str(tx.get("orderID") or tx.get("id") or "")
                    if oid:
                        try:
                            return self.order(oid)
                        except OandaError:
                            return {"id": oid, "status": "unknown", "filled": 0, "average": 0.0,
                                    "price": 0.0, "clientOrderId": client_order_id}
        return None

    def find_order_by_client_id(self, client_order_id: str, count: int = 500) -> dict[str, Any] | None:
        # OANDA supports an OrderSpecifier using @<clientOrderID>; use the
        # direct lookup first, with a bounded history fallback for older/demo
        # account behavior. This mirrors the official v20 API semantics.
        try:
            data = self._request(
                "GET",
                f"/v3/accounts/{self.config.account_id}/orders/@{client_order_id}",
            )
            order = data.get("order") or {}
            if order:
                return self.order(str(order.get("id") or ""))
        except OandaError:
            pass
        data = self._request("GET", f"/v3/accounts/{self.config.account_id}/orders",
                             params={"count": min(max(count, 1), 500)})
        for order in data.get("orders") or []:
            ext = order.get("clientExtensions") or {}
            if str(ext.get("id") or "") == client_order_id:
                return self.order(str(order.get("id")))
        return None

    def account_changes(self, since_transaction_id: str) -> dict[str, Any]:
        """Return OANDA's authoritative account snapshot and changes since a cursor.

        OANDA recommends persisting lastTransactionID and polling this endpoint to
        keep an account snapshot current; this is safer than reconstructing state
        from a bounded order-history query.
        """
        if not since_transaction_id:
            raise OandaError("A transaction cursor is required for account changes")
        return self._request(
            "GET",
            f"/v3/accounts/{self.config.account_id}/changes",
            params={"sinceTransactionID": str(since_transaction_id)},
        )

    def transactions_since(self, transaction_id: str) -> dict[str, Any]:
        """Return account transactions after transaction_id for durable reconciliation."""
        if not transaction_id:
            raise OandaError("A transaction ID is required for incremental reconciliation")
        return self._request(
            "GET",
            f"/v3/accounts/{self.config.account_id}/transactions/sinceid",
            params={"id": str(transaction_id)},
        )

    def transaction_stream_url(self) -> str:
        return ("https://stream-fxpractice.oanda.com" if self.config.practice
                else "https://stream-fxtrade.oanda.com") + f"/v3/accounts/{self.config.account_id}/transactions/stream"

    @staticmethod
    def parse_stream_line(line: str) -> dict[str, Any] | None:
        """Parse one OANDA JSON-lines stream record; blank/malformed lines are ignored."""
        import json
        raw = (line or "").strip()
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def orders(self, count: int = 500) -> list[dict[str, Any]]:
        data = self._request("GET", f"/v3/accounts/{self.config.account_id}/orders",
                             params={"count": min(max(count, 1), 500)})
        return data.get("orders") or []

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._request("PUT", f"/v3/accounts/{self.config.account_id}/orders/{order_id}/cancel")

    def positions(self) -> list[dict[str, Any]]:
        return self._request("GET", f"/v3/accounts/{self.config.account_id}/openPositions").get("positions") or []

    def position(self, instrument: str) -> dict[str, Any]:
        return self._request("GET", f"/v3/accounts/{self.config.account_id}/positions/{instrument}").get("position") or {}

    def close_position(self, instrument: str, long_units: str = "NONE", short_units: str = "NONE") -> dict[str, Any]:
        return self._request("PUT", f"/v3/accounts/{self.config.account_id}/positions/{instrument}/close",
                             json={"longUnits": long_units, "shortUnits": short_units})
