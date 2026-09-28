from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DerivConfig:
    app_id: int
    token: str
    account_id: str = ""
    endpoint: str = "wss://ws.derivws.com/websockets/v3"
    otp_endpoint: str = "https://api.derivws.com/trading/v1/options/accounts"
    timeout_seconds: float = 10.0
    live: bool = False


class DerivError(RuntimeError):
    pass


class DerivUnknown(DerivError):
    pass


class DerivBroker:
    """Customer-scoped Deriv trading adapter.

    Uses Deriv's current authenticated WebSocket workflow: bearer token -> account OTP
    -> authenticated demo/real WebSocket. No platform token fallback is permitted for
    customer execution.
    """
    def __init__(self, config: DerivConfig):
        if not config.app_id or not config.token:
            raise DerivError("Deriv app ID and API token are required")
        if config.live and not config.account_id:
            raise DerivError("Deriv real-account ID is required for live execution")
        self.config = config

    async def _auth_ws_url(self) -> str:
        import httpx
        if not self.config.account_id:
            return f"{self.config.endpoint}?app_id={self.config.app_id}"
        url = f"{self.config.otp_endpoint}/{self.config.account_id}/otp"
        headers = {"Authorization": f"Bearer {self.config.token}", "Deriv-App-ID": str(self.config.app_id)}
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                r = await client.post(url, headers=headers)
                if r.status_code >= 400:
                    raise DerivError(f"Deriv OTP HTTP {r.status_code}: {r.text[:500]}")
                body = r.json()
            ws_url = str(((body.get("data") or {}).get("url")) or "")
            if not ws_url.startswith("wss://"):
                raise DerivError("Deriv OTP returned no authenticated WebSocket URL")
            return ws_url
        except DerivError:
            raise
        except Exception as exc:
            raise DerivUnknown(f"Deriv authentication failed: {exc}") from exc

    async def _call(self, payload: dict[str, Any], *, authenticated: bool = True) -> dict[str, Any]:
        try:
            import websockets
            url = await self._auth_ws_url() if authenticated else f"{self.config.endpoint}?app_id={self.config.app_id}"
            async with websockets.connect(url, open_timeout=self.config.timeout_seconds, close_timeout=self.config.timeout_seconds, max_size=2_000_000) as ws:
                await asyncio.wait_for(ws.send(json.dumps(payload)), self.config.timeout_seconds)
                while True:
                    data = json.loads(await asyncio.wait_for(ws.recv(), self.config.timeout_seconds))
                    if data.get("error"):
                        err = data["error"]
                        raise DerivError(f"Deriv {err.get('code')}: {err.get('message')}")
                    req_id = payload.get("req_id")
                    if req_id is None or data.get("req_id") == req_id or data.get("echo_req", {}).get("req_id") == req_id:
                        return data
        except DerivError:
            raise
        except (TimeoutError, asyncio.TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise DerivUnknown(str(exc)) from exc
        except Exception as exc:
            raise DerivUnknown(str(exc)) from exc

    async def authorize(self) -> dict[str, Any]:
        return await self._call({"authorize": self.config.token, "req_id": 1}, authenticated=False)

    async def account(self) -> dict[str, Any]:
        return await self._call({"balance": 1, "req_id": 1}, authenticated=True)

    async def balance(self) -> dict[str, Any]:
        return await self._call({"balance": 1, "req_id": 2}, authenticated=True)

    async def active_symbols(self, market: str | None = None) -> list[dict[str, Any]]:
        data = await self._call({"active_symbols": "brief", "product_type": "basic", "req_id": 3}, authenticated=False)
        rows = data.get("active_symbols") or []
        if market:
            return [x for x in rows if str(x.get("market", "")).lower() == market.lower()]
        return rows

    async def proposal(self, **params: Any) -> dict[str, Any]:
        return await self._call({"proposal": 1, "req_id": 4, **params}, authenticated=True)

    async def buy(self, proposal_id: str, price: float, passthrough: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.config.live:
            raise DerivError("Deriv live execution is disabled")
        payload: dict[str, Any] = {"buy": proposal_id, "price": price, "req_id": 5}
        if passthrough: payload["passthrough"] = passthrough
        return await self._call(payload, authenticated=True)

    async def sell(self, contract_id: str, price: float = 0, passthrough: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.config.live:
            raise DerivError("Deriv live execution is disabled")
        payload: dict[str, Any] = {"sell": contract_id, "price": price, "req_id": 6}
        if passthrough: payload["passthrough"] = passthrough
        return await self._call(payload, authenticated=True)

    async def open_contract(self, contract_id: str, subscribe: bool = False) -> dict[str, Any]:
        return await self._call({"proposal_open_contract": 1, "contract_id": int(contract_id), "subscribe": int(subscribe), "req_id": 7}, authenticated=True)

    async def portfolio(self) -> dict[str, Any]:
        return await self._call({"portfolio": 1, "req_id": 8}, authenticated=True)

    async def preflight(self, currency: str | None = None) -> dict[str, Any]:
        auth = await self._call({"authorize": self.config.token, "req_id": 1}, authenticated=False)
        auth_data = auth.get("authorize") or {}
        loginid = str(auth_data.get("loginid") or "")
        scopes = auth_data.get("scopes") or auth_data.get("scope") or []
        if isinstance(scopes, str):
            scopes = [x for x in scopes.replace(",", " ").split() if x]
        scopes = [str(x).lower() for x in scopes]
        trade_scope = "trade" in scopes
        if self.config.account_id and loginid and loginid != self.config.account_id:
            # PAT may authorize a multi-account token; verify the requested account via OTP as well.
            await self._auth_ws_url()
            balance = await self.balance()
        else:
            balance = await self.balance()
        currency = currency or str(auth_data.get("currency") or (balance.get("balance") or {}).get("currency") or "USD")
        symbols = await self.active_symbols()
        return {"connected": True, "account_id": self.config.account_id or loginid, "currency": currency,
                "balance": (balance.get("balance") or {}).get("balance"), "symbols_available": len(symbols),
                "scopes": scopes, "trade_scope": trade_scope,
                "live_execution_enabled": bool(self.config.live), "execution_authority": bool(self.config.live and trade_scope)}
