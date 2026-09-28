from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Protocol
import httpx

from .config import settings


class PayoutError(Exception):
    pass

class PayoutUnknown(PayoutError):
    """The provider may have accepted the payout but its response was lost."""

@dataclass
class PayoutResult:
    provider: str
    provider_id: str
    status: str
    raw_status: str = ""
    detail: dict[str, Any] | None = None

class PayoutProvider(Protocol):
    name: str
    async def send(self, *, currency: str, amount: float, destination: str, tag: str | None,
                   network: str | None, idempotency_key: str, metadata: dict[str, Any]) -> PayoutResult: ...
    async def status(self, provider_id: str, *, currency: str | None = None) -> PayoutResult: ...
    async def recover(self, idempotency_key: str, *, currency: str | None = None) -> PayoutResult: ...


class CCXTPayoutProvider:
    name = "ccxt"

    def __init__(self):
        if not settings.exchange_api_key or not settings.exchange_api_secret:
            raise PayoutError("Exchange payout credentials are not configured")
        try:
            import ccxt
        except ImportError as e:
            raise PayoutError("CCXT is not installed") from e
        exchange_cls = getattr(ccxt, settings.default_exchange, None)
        if exchange_cls is None:
            raise PayoutError(f"Unsupported CCXT exchange: {settings.default_exchange}")
        self.exchange = exchange_cls({
            "apiKey": settings.exchange_api_key,
            "secret": settings.exchange_api_secret,
            "password": settings.exchange_password or None,
            "enableRateLimit": True,
            "timeout": settings.exchange_timeout_ms,
        })
        # CCXT requires sandbox mode before any other exchange call.
        if settings.broker_sandbox:
            self.exchange.set_sandbox_mode(True)

    async def _call(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def send(self, *, currency, amount, destination, tag, network, idempotency_key, metadata):
        if not self.exchange.has.get("withdraw"):
            raise PayoutError(f"{self.exchange.id} does not advertise withdrawal support")
        params = {"clientOrderId": idempotency_key}
        if network:
            params["network"] = network
        # Some exchanges reject unsupported clientOrderId; callers must reconcile on UNKNOWN.
        try:
            tx = await self._call(self.exchange.withdraw, currency, amount, destination, tag, params)
        except Exception as e:
            msg = str(e).lower()
            if any(x in msg for x in ("timeout", "timed out", "network", "connection")):
                raise PayoutUnknown(str(e)) from e
            raise PayoutError(str(e)) from e
        provider_id = str(tx.get("id") or tx.get("txid") or "")
        if not provider_id:
            raise PayoutUnknown("Exchange accepted/returned an ambiguous withdrawal without an id")
        return PayoutResult(self.name, provider_id, "SUBMITTED", str(tx.get("status") or ""), tx)

    async def status(self, provider_id, *, currency=None):
        try:
            tx = await self._call(self.exchange.fetch_withdrawal, provider_id, currency)
        except Exception as e:
            raise PayoutUnknown(str(e)) from e
        status = str(tx.get("status") or "unknown").upper()
        mapped = {"OK": "COMPLETED", "SUCCESS": "COMPLETED", "DONE": "COMPLETED",
                  "FAILED": "FAILED", "CANCELED": "FAILED", "CANCELLED": "FAILED",
                  "PENDING": "PENDING"}.get(status, "PENDING")
        return PayoutResult(self.name, provider_id, mapped, status, tx)


    async def recover(self, idempotency_key: str, *, currency: str | None = None) -> PayoutResult:
        if not self.exchange.has.get("fetchWithdrawals"):
            raise PayoutError(f"{self.exchange.id} does not support withdrawal history lookup")
        try:
            rows = await self._call(self.exchange.fetch_withdrawals, currency, None, 100)
        except Exception as e:
            raise PayoutUnknown(str(e)) from e
        for tx in rows or []:
            raw = tx or {}
            info = raw.get("info") or {}
            if idempotency_key in json.dumps(raw, sort_keys=True) or idempotency_key == str(info.get("clientOrderId") or info.get("idempotency_key") or ""):
                provider_id = str(raw.get("id") or raw.get("txid") or "")
                if provider_id:
                    raw_status = str(raw.get("status") or "PENDING").upper()
                    mapped = {"OK":"COMPLETED","SUCCESS":"COMPLETED","DONE":"COMPLETED","FAILED":"FAILED","CANCELED":"FAILED","CANCELLED":"FAILED"}.get(raw_status, "PENDING")
                    return PayoutResult(self.name, provider_id, mapped, raw_status, raw)
        raise PayoutUnknown("No matching withdrawal was found in provider history")


class GenericBankProvider:
    """Provider-neutral bank adapter. Configure the bank/payment processor's exact endpoint and contract."""
    name = "bank_http"

    async def send(self, *, currency, amount, destination, tag, network, idempotency_key, metadata):
        if not settings.bank_payout_url or not settings.bank_payout_hmac_secret:
            raise PayoutError("Bank payout provider is not configured")
        payload = {
            "idempotency_key": idempotency_key,
            "currency": currency,
            "amount": amount,
            "destination": destination,
            "metadata": metadata,
        }
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        signature = hmac.new(settings.bank_payout_hmac_secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=settings.bank_payout_timeout_seconds) as client:
                r = await client.post(settings.bank_payout_url, content=body,
                                      headers={"Content-Type": "application/json",
                                               "Idempotency-Key": idempotency_key,
                                               "X-Signature-SHA256": signature})
                r.raise_for_status()
                data = r.json()
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise PayoutUnknown(str(e)) from e
        except Exception as e:
            raise PayoutError(str(e)) from e
        provider_id = str(data.get("id") or data.get("transaction_id") or "")
        if not provider_id:
            raise PayoutUnknown("Bank provider returned no transaction id")
        return PayoutResult(self.name, provider_id, str(data.get("status", "SUBMITTED")).upper(), detail=data)

    async def recover(self, idempotency_key: str, *, currency: str | None = None) -> PayoutResult:
        template = getattr(settings, "bank_status_by_idempotency_url_template", "")
        if not template:
            raise PayoutError("Bank provider does not expose idempotency-key recovery")
        url = template.format(idempotency_key=idempotency_key)
        sig = hmac.new(settings.bank_payout_hmac_secret.encode(), idempotency_key.encode(), hashlib.sha256).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=settings.bank_payout_timeout_seconds) as client:
                r = await client.get(url, headers={"X-Signature-SHA256": sig, "Idempotency-Key": idempotency_key})
                r.raise_for_status()
                data = r.json()
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise PayoutUnknown(str(e)) from e
        except Exception as e:
            raise PayoutError(str(e)) from e
        provider_id = str(data.get("id") or data.get("transaction_id") or "")
        if not provider_id:
            raise PayoutUnknown("Bank provider returned no transaction id for idempotency key")
        raw = str(data.get("status", "PENDING")).upper()
        mapped = {"COMPLETED":"COMPLETED","SUCCESS":"COMPLETED","FAILED":"FAILED","REJECTED":"FAILED"}.get(raw, "PENDING")
        return PayoutResult(self.name, provider_id, mapped, raw, data)

    async def status(self, provider_id, *, currency=None):
        if not settings.bank_status_url_template or not settings.bank_payout_hmac_secret:
            raise PayoutError("Bank payout status contract is not configured")
        url = settings.bank_status_url_template.format(provider_id=provider_id)
        sig = hmac.new(settings.bank_payout_hmac_secret.encode(), provider_id.encode(), hashlib.sha256).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=settings.bank_payout_timeout_seconds) as client:
                r = await client.get(url, headers={"X-Signature-SHA256": sig})
                r.raise_for_status()
                data = r.json()
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise PayoutUnknown(str(e)) from e
        except Exception as e:
            raise PayoutError(str(e)) from e
        raw = str(data.get("status", "PENDING")).upper()
        mapped = {"COMPLETED":"COMPLETED", "SUCCESS":"COMPLETED", "FAILED":"FAILED", "REJECTED":"FAILED"}.get(raw, "PENDING")
        return PayoutResult(self.name, provider_id, mapped, raw, data)


class ExternalSignerPayoutProvider:
    """Custody boundary: Atlas sends an authenticated intent to an external signer/MPC service.

    The signer, private key/MPC quorum and blockchain broadcast remain outside Atlas. The
    service must return a provider transaction id and expose status/recovery endpoints.
    """
    name = "external_signer"

    def __init__(self):
        from .custody_signer import validate_signer_config
        validate_signer_config()
        self.url = settings.external_custody_signer_url.rstrip("/")
        self.secret = settings.external_custody_signer_hmac_secret

    async def _request(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()
        sig = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=settings.bank_payout_timeout_seconds) as client:
                r = await client.post(self.url + path, content=body, headers={"Content-Type":"application/json","X-Signature-SHA256":sig})
                r.raise_for_status(); return r.json()
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise PayoutUnknown(str(e)) from e
        except Exception as e:
            raise PayoutError(str(e)) from e

    async def send(self, *, currency, amount, destination, tag, network, idempotency_key, metadata):
        data = await self._request("/sign-and-broadcast", {"currency":currency,"amount":amount,"destination":destination,"tag":tag,"network":network,"idempotency_key":idempotency_key,"metadata":metadata})
        provider_id = str(data.get("provider_id") or data.get("transaction_id") or data.get("txid") or "")
        if not provider_id: raise PayoutUnknown("External signer returned no transaction id")
        return PayoutResult(self.name, provider_id, str(data.get("status") or "SUBMITTED").upper(), detail=data)

    async def status(self, provider_id, *, currency=None):
        data = await self._request("/status", {"provider_id":provider_id,"currency":currency})
        raw=str(data.get("status") or "PENDING").upper(); mapped={"COMPLETED":"COMPLETED","SUCCESS":"COMPLETED","FAILED":"FAILED","REJECTED":"FAILED"}.get(raw,"PENDING")
        return PayoutResult(self.name,provider_id,mapped,raw,data)

    async def recover(self, idempotency_key, *, currency=None):
        data = await self._request("/recover", {"idempotency_key":idempotency_key,"currency":currency})
        provider_id=str(data.get("provider_id") or data.get("transaction_id") or data.get("txid") or "")
        if not provider_id: raise PayoutUnknown("External signer recovery returned no transaction id")
        raw=str(data.get("status") or "PENDING").upper(); mapped={"COMPLETED":"COMPLETED","SUCCESS":"COMPLETED","FAILED":"FAILED","REJECTED":"FAILED"}.get(raw,"PENDING")
        return PayoutResult(self.name,provider_id,mapped,raw,data)


def get_payout_provider(provider: str | None = None) -> PayoutProvider:
    selected = (provider or settings.payout_provider).lower()
    if selected == "ccxt" and settings.environment.lower() in {"production", "staging"}:
        raise PayoutError("Direct CCXT withdrawals are disabled outside development; use the external signer custody boundary")
    if settings.external_custody_signer_required and selected == "ccxt":
        raise PayoutError("External custody signer is required; direct exchange withdrawals are disabled")
    if selected == "external_signer":
        return ExternalSignerPayoutProvider()
    if selected == "ccxt":
        return CCXTPayoutProvider()
    if selected == "bank_http":
        return GenericBankProvider()
    raise PayoutError("No payout provider configured. Use PAYOUT_PROVIDER=external_signer or bank_http; ccxt is development-only.")
