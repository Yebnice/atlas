from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import ccxt.async_support as ccxt

@dataclass(frozen=True)
class ExchangeCapability:
    exchange: str
    create_order: bool
    cancel_order: bool
    fetch_order: bool
    fetch_open_orders: bool
    fetch_balance: bool
    fetch_positions: bool
    websocket_available: bool = False

class ExchangeAdapter:
    """Small Atlas boundary around CCXT's unified API. Exchange-specific methods remain accessible on the client when needed."""
    def __init__(self, exchange_id: str, *, api_key: str = "", secret: str = "", password: str = "", timeout_ms: int = 10000):
        exchange_id = str(exchange_id).lower().strip()
        cls = getattr(ccxt, exchange_id, None)
        if cls is None:
            raise ValueError(f"Unsupported CCXT exchange: {exchange_id}")
        self.client = cls({
            "apiKey": api_key, "secret": secret, "password": password,
            "enableRateLimit": True, "timeout": max(1000, int(timeout_ms)),
        })

    async def load_markets(self):
        return await self.client.load_markets()

    def capabilities(self) -> ExchangeCapability:
        has = getattr(self.client, "has", {}) or {}
        return ExchangeCapability(
            exchange=str(self.client.id),
            create_order=bool(has.get("createOrder")),
            cancel_order=bool(has.get("cancelOrder")),
            fetch_order=bool(has.get("fetchOrder")),
            fetch_open_orders=bool(has.get("fetchOpenOrders")),
            fetch_balance=bool(has.get("fetchBalance")),
            fetch_positions=bool(has.get("fetchPositions")),
            websocket_available=False,
        )

    async def fetch_order_state(self, order_id: str, symbol: str | None = None) -> dict[str, Any]:
        if not self.capabilities().fetch_order:
            raise NotImplementedError(f"{self.client.id} does not expose fetchOrder through the unified adapter")
        return await self.client.fetch_order(order_id, symbol)

    async def close(self):
        await self.client.close()
