from __future__ import annotations
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .binance_arb_reconcile import validate_symbol_filters, partial_leg_exposure, neutralization_side, BinanceArbRecoveryError


@dataclass(frozen=True)
class BinanceArbConfig:
    api_key: str
    api_secret: str
    sandbox: bool = True
    live_enabled: bool = False
    fee_rate: float = 0.001
    max_capital_usdt: float = 1000.0
    max_quote_age_ms: int = 750
    min_net_edge_pct: float = 0.10


class BinanceArbitrageError(RuntimeError):
    pass


class BinanceArbitrageBroker:
    """Conservative Binance spot triangular-arbitrage execution adapter.

    Live execution is disabled by default. Legs are IOC orders and every leg is
    reconciled; a later leg is never submitted after an unresolved prior leg.
    This is not atomic multi-leg execution and therefore includes a hard exposure
    cap and an UNKNOWN state for interrupted legs.
    """
    def __init__(self, config: BinanceArbConfig):
        self.config = config
        self.exchange = None

    def connect(self):
        if not self.config.api_key or not self.config.api_secret:
            raise BinanceArbitrageError("Binance API credentials are required")
        import ccxt
        exchange = ccxt.binance({
            "apiKey": self.config.api_key,
            "secret": self.config.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })
        if self.config.sandbox:
            exchange.set_sandbox_mode(True)
        exchange.load_markets()
        self.exchange = exchange
        return exchange

    def _c(self):
        return self.exchange or self.connect()

    def preflight(self, symbols: list[str]) -> dict[str, Any]:
        c = self._c()
        missing = [s for s in symbols if s not in c.markets]
        balance = c.fetch_balance()
        return {
            "exchange": "binance",
            "sandbox": self.config.sandbox,
            "live_execution_enabled": self.config.live_enabled,
            "execution_authority": bool(self.config.live_enabled),
            "symbols_supported": not missing,
            "missing_symbols": missing,
            "balances_available": bool(balance),
        }

    def quote(self, symbol: str) -> dict[str, Any]:
        t = self._c().fetch_ticker(symbol)
        ts = t.get("timestamp")
        if ts is None:
            raise BinanceArbitrageError("Binance quote has no timestamp")
        age = max(0, int(time.time() * 1000) - int(ts))
        if age > self.config.max_quote_age_ms:
            raise BinanceArbitrageError(f"Binance quote is stale: {age}ms")
        bid, ask = float(t.get("bid") or 0), float(t.get("ask") or 0)
        if bid <= 0 or ask <= 0 or ask < bid:
            raise BinanceArbitrageError("Invalid Binance bid/ask")
        return {"bid": bid, "ask": ask, "bidVolume": float(t.get("bidVolume") or 0), "askVolume": float(t.get("askVolume") or 0), "timestamp": ts, "age_ms": age}

    def execute_ioc_leg(self, symbol: str, side: str, amount: float, limit_price: float, client_id: str | None = None) -> dict[str, Any]:
        if not self.config.live_enabled:
            raise BinanceArbitrageError("Binance arbitrage live execution is disabled")
        client_id = client_id or f"atlas-arb-{uuid.uuid4().hex[:20]}"
        try:
            price = float(self._c().price_to_precision(symbol, limit_price))
            # Binance Spot supports LIMIT + IOC; this bounds price rather than using an unbounded market order.
            return self._c().create_order(symbol, "limit", side.lower(), amount, price, {
                "timeInForce": "IOC",
                "newClientOrderId": client_id,
            })
        except Exception as exc:
            # Never retry an ambiguous arbitrage leg automatically.
            raise BinanceArbitrageError(f"UNKNOWN Binance arbitrage leg {client_id}: {exc}") from exc

    def order_status(self, symbol: str, order_id: str) -> dict[str, Any]:
        return self._c().fetch_order(order_id, symbol)

    def neutralize_partial_leg(self, symbol: str, side: str, base_asset: str, requested: float, receipt: dict[str, Any]) -> dict[str, Any]:
        """Neutralize a partial leg with one bounded IOC order.

        This is recovery-only: it never advances the arbitrage cycle. A fresh
        quote is required and the neutralization amount is capped by the
        configured arbitrage capital limit.
        """
        if not self.config.live_enabled:
            raise BinanceArbitrageError("Binance arbitrage live execution is disabled")
        exposure = partial_leg_exposure(receipt, side, base_asset, requested)
        if not exposure.needs_flatten:
            return {"status": "NO_EXPOSURE", "asset": exposure.asset, "quantity": 0.0}
        quote = self.quote(symbol)
        recovery_side = neutralization_side(exposure)
        amount = abs(exposure.quantity)
        px = quote["bid"] if recovery_side == "SELL" else quote["ask"]
        notional = amount * px
        if notional > self.config.max_capital_usdt:
            raise BinanceArbitrageError("Neutralization exceeds configured arbitrage capital cap")
        markets = self._c().markets
        info = markets.get(symbol) or {}
        validate_symbol_filters(info, recovery_side, amount, px, notional)
        return self.execute_ioc_leg(symbol, recovery_side, amount, px, client_id=f"atlas-recover-{uuid.uuid4().hex[:20]}")

    def find_order_by_client_id(self, symbol: str, client_order_id: str) -> dict[str, Any] | None:
        if not client_order_id:
            raise BinanceArbitrageError("client order ID is required")
        c = self._c()
        # CCXT exposes exchange-native client-order-id lookup inconsistently.
        # Prefer the raw Binance REST method when available; otherwise search
        # recent orders and require an exact clientOrderId match.
        raw = getattr(c, "fetch_open_orders", None)
        if raw:
            try:
                for order in raw(symbol):
                    if str(order.get("clientOrderId") or order.get("info", {}).get("clientOrderId") or "") == client_order_id:
                        return order
            except Exception:
                pass
        try:
            orders = c.fetch_orders(symbol, limit=500)
            for order in orders:
                if str(order.get("clientOrderId") or order.get("info", {}).get("clientOrderId") or "") == client_order_id:
                    return order
        except Exception:
            pass
        return None
