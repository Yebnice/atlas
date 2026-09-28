from __future__ import annotations
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from .config import settings


def _pairs(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in (raw or '').split(','):
        if ':' in item:
            k, v = item.split(':', 1)
            if k.strip() and v.strip(): out[k.strip()] = v.strip()
    return out


def verify_release_operator(operator_id: str, token: str | None) -> bool:
    expected = _pairs(settings.withdrawal_release_tokens).get(operator_id)
    return bool(expected and token and hmac.compare_digest(token, expected))


def destination_fingerprint(destination: str, currency: str, network: str = '') -> str:
    raw = f'{currency.upper()}|{network.upper()}|{destination.strip()}'.encode()
    return hashlib.sha256(raw).hexdigest()


def destination_allowed(destination: str, currency: str, network: str = '') -> bool:
    if not settings.withdrawal_whitelist_enabled:
        return False if settings.environment == 'production' else True
    allowed = {x.strip().lower() for x in settings.withdrawal_destination_fingerprints.split(',') if x.strip()}
    if not allowed:
        return settings.environment != 'production'
    return destination_fingerprint(destination, currency, network).lower() in allowed


def _canonical_decimal(value: Any) -> str:
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("proposal amount must be a valid decimal") from exc
    if not d.is_finite():
        raise ValueError("proposal amount must be finite")
    if d == 0:
        d = Decimal(0)
    # Fixed-point, normalized text avoids float formatting ambiguity across runtimes/platforms.
    text = format(d, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def canonical_proposal(*, request_id: str, amount: float | Decimal, currency: str, destination: str,
                       tag: str = '', network: str = '', provider: str = '') -> bytes:
    payload = {
        'request_id': request_id, 'amount': _canonical_decimal(amount), 'currency': currency.upper(),
        'destination': destination, 'tag': tag, 'network': network, 'provider': provider,
    }
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()


def proposal_digest(**kwargs: Any) -> str:
    return hashlib.sha256(canonical_proposal(**kwargs)).hexdigest()
