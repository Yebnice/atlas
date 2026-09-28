from __future__ import annotations
from dataclasses import dataclass
from threading import RLock
from typing import Any
import hashlib


@dataclass
class BrokerConfig:
    exchange_id: str
    api_key: str
    api_secret: str
    password: str = ""
    sandbox: bool = True
    market_type: str = "swap"
    timeout_ms: int = 10_000


class Broker:
    _instances: dict[str, "Broker"] = {}
    _global_lock = RLock()

    def __init__(self, config: BrokerConfig):
        self.config = config
        self.client = None
        self._lock = RLock()

    @classmethod
    def get(cls, config: BrokerConfig) -> "Broker":
        credential_id = hashlib.sha256(config.api_key.encode("utf-8")).hexdigest()
        key = f"{config.exchange_id}:{credential_id}:{config.sandbox}:{config.market_type}"
        with cls._global_lock:
            if key not in cls._instances:
                cls._instances[key] = Broker(config)
            return cls._instances[key]

    def connect(self):
        with self._lock:
            if self.client is not None:
                return self.client
            if not self.config.api_key or not self.config.api_secret:
                raise RuntimeError("Broker credentials are not configured")
            import ccxt
            if self.config.exchange_id not in ccxt.exchanges:
                raise RuntimeError(f"Unsupported CCXT exchange: {self.config.exchange_id}")
            cls = getattr(ccxt, self.config.exchange_id)
            params = {
                "apiKey": self.config.api_key,
                "secret": self.config.api_secret,
                "enableRateLimit": True,
                "timeout": self.config.timeout_ms,
                "options": {"defaultType": self.config.market_type},
            }
            if self.config.password:
                params["password"] = self.config.password
            client = cls(params)
            # CCXT requires sandbox mode to be enabled before any other exchange call.
            if self.config.sandbox:
                client.set_sandbox_mode(True)
            client.load_markets()
            self.client = client
            return client

    def _c(self):
        return self.client or self.connect()

    def ticker(self, symbol: str) -> dict[str, Any]:
        with self._lock:
            return self._c().fetch_ticker(symbol)

    def market_info(self, symbol: str) -> dict[str, Any]:
        with self._lock:
            market = self._c().market(symbol)
            return market

    def normalize_amount(self, symbol: str, amount: float) -> float:
        with self._lock:
            c = self._c()
            return float(c.amount_to_precision(symbol, amount))

    def normalize_price(self, symbol: str, price: float) -> float:
        with self._lock:
            c = self._c()
            return float(c.price_to_precision(symbol, price))

    def market_order(self, symbol: str, side: str, amount: float, client_order_id: str,
                     stop_loss_price: float | None = None, take_profit_price: float | None = None,
                     reduce_only: bool = False) -> dict[str, Any]:
        with self._lock:
            c = self._c()
            params: dict[str, Any] = {"clientOrderId": client_order_id}
            if reduce_only:
                params["reduceOnly"] = True
            if stop_loss_price is not None:
                params["stopLoss"] = {"triggerPrice": stop_loss_price, "type": "market"}
            if take_profit_price is not None:
                params["takeProfit"] = {"triggerPrice": take_profit_price, "type": "market"}
            # Do not blindly retry market orders. A timeout can mean the exchange accepted the order.
            return c.create_order(symbol, "market", side, amount, None, params)

    def fetch_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        with self._lock:
            return self._c().fetch_order(order_id, symbol)

    def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return self._c().fetch_open_orders(symbol) if symbol else self._c().fetch_open_orders()

    def fetch_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            c = self._c()
            if not c.has.get("fetchOrders"):
                return []
            return c.fetch_orders(symbol) if symbol else c.fetch_orders()

    def fetch_balance(self) -> dict[str, Any]:
        with self._lock:
            return self._c().fetch_balance()

    def fetch_positions(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            c = self._c()
            if not c.has.get("fetchPositions"):
                return []
            return c.fetch_positions(symbols)

    def cancel_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        with self._lock:
            return self._c().cancel_order(order_id, symbol)

    def cancel_all_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            c = self._c()
            if c.has.get("cancelAllOrders"):
                result = c.cancel_all_orders(symbol) if symbol else c.cancel_all_orders()
                return result if isinstance(result, list) else [result]
            orders = self.fetch_open_orders(symbol)
            out = []
            for order in orders:
                oid = order.get("id")
                sym = order.get("symbol") or symbol
                if oid and sym:
                    try:
                        out.append(c.cancel_order(oid, sym))
                    except Exception:
                        pass
            return out

    def server_time(self) -> int | None:
        with self._lock:
            c = self._c()
            return c.fetch_time() if c.has.get("fetchTime") else None

    def feature_value(self, symbol: str, feature: str):
        with self._lock:
            c = self._c()
            return c.feature_value(symbol, "createOrder", feature)

    def supports_feature(self, symbol: str, feature: str) -> bool:
        try:
            return bool(self.feature_value(symbol, feature))
        except Exception:
            return False

    def features(self, symbol: str) -> dict[str, Any]:
        with self._lock:
            c = self._c()
            return getattr(c, "features", {}) or {}
