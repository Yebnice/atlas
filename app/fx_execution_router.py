from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal
import math
import time


Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class FXQuote:
    provider: str
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    timestamp_ms: int
    maker_fee_bps: float = 0.0
    taker_fee_bps: float = 0.0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class FXRoutePlan:
    symbol: str
    side: Side
    quantity: float
    provider: str | None
    executable_price: float
    spread_bps: float
    fee_bps: float
    latency_buffer_bps: float
    total_cost_bps: float
    stale: bool
    sufficient_depth: bool
    order_type: Literal["RFQ", "LIMIT", "NO_TRADE"]
    rationale: str
    execution_authority: bool = False
    mode: str = "RESEARCH_ONLY"


def _validate_quote(q: FXQuote) -> None:
    if not q.provider or not q.symbol:
        raise ValueError("provider and symbol are required")
    if q.bid <= 0 or q.ask <= 0 or q.ask < q.bid:
        raise ValueError("invalid FX quote")
    if q.bid_size < 0 or q.ask_size < 0:
        raise ValueError("quote sizes cannot be negative")
    if q.maker_fee_bps < 0 or q.taker_fee_bps < 0:
        raise ValueError("fees cannot be negative")
    if q.latency_ms < 0:
        raise ValueError("latency cannot be negative")


def route_fx_quotes(
    *,
    symbol: str,
    side: Side,
    quantity: float,
    quotes: list[FXQuote],
    now_ms: int | None = None,
    max_quote_age_ms: int = 1_500,
    max_latency_ms: float = 500.0,
    short_term_vol_bps_per_s: float = 0.0,
    max_total_cost_bps: float = 3.0,
) -> FXRoutePlan:
    """Research-only multi-LP FX route selector. It never places an order."""
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if short_term_vol_bps_per_s < 0 or max_total_cost_bps < 0:
        raise ValueError("cost inputs cannot be negative")
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    valid: list[tuple[FXQuote, float, float, float, float]] = []

    for q in quotes:
        _validate_quote(q)
        if q.symbol != symbol:
            continue
        age = max(0, now - int(q.timestamp_ms))
        stale = age > max_quote_age_ms
        if stale or q.latency_ms > max_latency_ms:
            continue
        price = q.ask if side == "buy" else q.bid
        depth = q.ask_size if side == "buy" else q.bid_size
        if depth < quantity:
            continue
        mid = (q.bid + q.ask) / 2.0
        spread_bps = (q.ask - q.bid) / mid * 10_000.0
        fee = q.taker_fee_bps
        latency_buffer = q.latency_ms / 1000.0 * short_term_vol_bps_per_s
        # The quote is already executable at the displayed side; spread is included as an explicit cost.
        total = (spread_bps / 2.0) + fee + latency_buffer
        valid.append((q, price, spread_bps, latency_buffer, total))

    if not valid:
        return FXRoutePlan(symbol, side, quantity, None, 0.0, 0.0, 0.0, 0.0, math.inf,
                           True, False, "NO_TRADE", "No fresh quote with sufficient executable depth", False)

    q, price, spread_bps, latency_buffer, total = min(valid, key=lambda x: x[4])
    if total > max_total_cost_bps:
        return FXRoutePlan(symbol, side, quantity, None, price, spread_bps, q.taker_fee_bps,
                           latency_buffer, total, False, True, "NO_TRADE",
                           "Best executable quote exceeds configured total-cost budget", False)

    return FXRoutePlan(symbol, side, quantity, q.provider, price, spread_bps, q.taker_fee_bps,
                       latency_buffer, total, False, True, "RFQ",
                       "Selected lowest modeled executable cost across fresh liquidity providers", False)
