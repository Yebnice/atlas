from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .config import settings

USDT_SCALE = Decimal("1000000")


class SweepError(Exception):
    pass


@dataclass(frozen=True)
class SweepIntent:
    wallet_id: int
    source_address: str
    treasury_address: str
    amount_usdt: Decimal
    raw_amount: int
    idempotency_key: str
    network: str = "TRON"
    contract: str = ""
    status: str = "READY_FOR_SIGNER"


def usdt_to_raw(amount: Decimal | str | float) -> int:
    value = Decimal(str(amount))
    if value <= 0:
        raise SweepError("sweep amount must be positive")
    raw = value * USDT_SCALE
    if raw != raw.to_integral_value():
        raise SweepError("USDT amount must have at most 6 decimal places")
    return int(raw)


def build_sweep_intent(*, wallet_id: int, source_address: str, amount_usdt: Decimal | str | float,
                       treasury_address: str | None = None, idempotency_key: str | None = None) -> SweepIntent:
    treasury = treasury_address or settings.usdt_tron_treasury_address
    if not source_address or not treasury:
        raise SweepError("source and treasury addresses are required")
    if source_address == treasury:
        raise SweepError("source address cannot equal treasury address")
    raw = usdt_to_raw(amount_usdt)
    key = idempotency_key or hashlib.sha256(
        f"tron-sweep:{wallet_id}:{source_address}:{treasury}:{raw}:{settings.usdt_tron_usdt_contract}".encode()
    ).hexdigest()
    return SweepIntent(wallet_id=wallet_id, source_address=source_address, treasury_address=treasury,
                       amount_usdt=Decimal(raw) / USDT_SCALE, raw_amount=raw,
                       idempotency_key=key, contract=settings.usdt_tron_usdt_contract)


def serialize_sweep_intent(intent: SweepIntent) -> dict[str, Any]:
    return {
        "wallet_id": intent.wallet_id,
        "source_address": intent.source_address,
        "treasury_address": intent.treasury_address,
        "amount_usdt": format(intent.amount_usdt, "f"),
        "raw_amount": str(intent.raw_amount),
        "network": intent.network,
        "contract": intent.contract,
        "idempotency_key": intent.idempotency_key,
        "status": intent.status,
    }

TRANSFER_TOPIC = "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a9df523b3ef"


def _hex_topic_to_tron_address(value: str) -> str | None:
    raw = (value or "").lower().removeprefix("0x")
    if len(raw) != 64:
        return None
    payload = bytes.fromhex(raw)
    try:
        from bip_utils import Base58Encoder
    except ImportError as exc:
        raise RuntimeError("bip-utils is required for TRON receipt address decoding") from exc
    # ABI address topics are 32-byte left-padded values; TRON address payload is 0x41 + 20 bytes.
    return Base58Encoder.CheckEncode(b"\x41" + payload[-20:])


def extract_trc20_transfer(receipt: dict[str, Any], contract: str, source: str, destination: str) -> int | None:
    """Return the raw USDT amount for a matching solidified Transfer event, else None."""
    for log in receipt.get("log", []) or receipt.get("logs", []) or []:
        topics = [str(x) for x in (log.get("topics") or [])]
        if len(topics) < 3 or topics[0].lower().removeprefix("0x") != TRANSFER_TOPIC:
            continue
        log_contract = str(log.get("address") or "")
        if log_contract.lower().removeprefix("0x") not in {contract.lower().removeprefix("0x"), contract.lower()}:
            continue
        from_addr = _hex_topic_to_tron_address(topics[1])
        to_addr = _hex_topic_to_tron_address(topics[2])
        data = str(log.get("data") or "").removeprefix("0x")
        if from_addr != source or to_addr != destination or len(data) != 64:
            continue
        return int(data, 16)
    return None


def classify_solidified_sweep(*, tx_body: dict[str, Any], receipt: dict[str, Any],
                              transaction_id: str, source: str, treasury: str, contract: str,
                              expected_raw_amount: int) -> tuple[str, dict[str, Any]]:
    """Classify a sweep only from solidified transaction body + receipt evidence."""
    if not tx_body or not receipt:
        return "PENDING_CONFIRMATION", {"reason": "solidified transaction/receipt not yet available"}
    if str(tx_body.get("txID") or tx_body.get("txid") or "").lower() != transaction_id.lower():
        return "REVIEW", {"reason": "transaction id mismatch"}
    ret = (tx_body.get("ret") or [{}])[0]
    if str(ret.get("contractRet") or "").upper() not in {"", "SUCCESS"}:
        return "FAILED", {"reason": f"contractRet={ret.get('contractRet')}"}
    if str(receipt.get("id") or "").lower() not in {"", transaction_id.lower()}:
        return "REVIEW", {"reason": "receipt id mismatch"}
    if str(receipt.get("result") or "").upper() == "FAILED":
        return "FAILED", {"reason": "solidified receipt result=FAILED"}
    receipt_result = str((receipt.get("receipt") or {}).get("result") or "").upper()
    if receipt_result != "SUCCESS":
        return "REVIEW", {"reason": f"solidified receipt result={receipt_result or 'missing'}"}
    observed = extract_trc20_transfer(receipt, contract, source, treasury)
    if observed is None:
        return "REVIEW", {"reason": "matching TRC-20 Transfer event not found"}
    if observed != expected_raw_amount:
        return "REVIEW", {"reason": "transfer amount mismatch", "observed_raw": observed,
                           "expected_raw": expected_raw_amount}
    return "SETTLED", {"observed_raw": observed}
