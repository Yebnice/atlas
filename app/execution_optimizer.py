from __future__ import annotations
from dataclasses import dataclass
from math import ceil
from typing import Literal


@dataclass(frozen=True)
class BookLevel:
    price: float
    quantity: float


@dataclass(frozen=True)
class ExecutionPlan:
    side: Literal["buy", "sell"]
    quantity: float
    reference_price: float
    executable_price: float
    spread_bps: float
    market_impact_bps: float
    fee_bps: float
    latency_buffer_bps: float
    total_cost_bps: float
    max_adverse_bps: float
    order_type: Literal["MARKET", "IOC_LIMIT", "LIMIT_MAKER", "NO_TRADE"]
    slices: int
    rationale: str


def _validate(levels: list[BookLevel], quantity: float) -> None:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if not levels:
        raise ValueError("order book is empty")
    for x in levels:
        if x.price <= 0 or x.quantity <= 0:
            raise ValueError("order book contains invalid level")


def executable_vwap(levels: list[BookLevel], quantity: float) -> tuple[float, float]:
    """Return VWAP and unfilled quantity using the executable side of the book."""
    _validate(levels, quantity)
    remaining = quantity
    notional = 0.0
    filled = 0.0
    for level in levels:
        take = min(remaining, level.quantity)
        notional += take * level.price
        filled += take
        remaining -= take
        if remaining <= 1e-12:
            break
    if filled <= 0:
        return 0.0, quantity
    return notional / filled, max(0.0, remaining)


def impact_bps(reference_price: float, executable_price: float, side: str) -> float:
    if reference_price <= 0 or executable_price <= 0:
        raise ValueError("prices must be positive")
    direction = 1 if side == "buy" else -1
    return max(0.0, direction * (executable_price / reference_price - 1.0) * 10_000)


def build_execution_plan(
    *,
    side: Literal["buy", "sell"],
    quantity: float,
    best_price: float,
    levels: list[BookLevel],
    maker_fee_bps: float,
    taker_fee_bps: float,
    latency_ms: float = 0.0,
    short_term_vol_bps_per_s: float = 0.0,
    max_adverse_bps: float = 50.0,
    urgency: float = 0.5,
) -> ExecutionPlan:
    """Cost-aware execution selector. This is a conservative planning model, not an HFT guarantee."""
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if maker_fee_bps < 0 or taker_fee_bps < 0:
        raise ValueError("fees cannot be negative")
    if latency_ms < 0 or short_term_vol_bps_per_s < 0:
        raise ValueError("latency/volatility cannot be negative")
    urgency = min(1.0, max(0.0, urgency))
    vwap, unfilled = executable_vwap(levels, quantity)
    if unfilled > 1e-12:
        return ExecutionPlan(side, quantity, best_price, vwap, 0.0, impact_bps(best_price, vwap, side), taker_fee_bps,
                             latency_ms / 1000.0 * short_term_vol_bps_per_s,
                             float("inf"), max_adverse_bps, "NO_TRADE", 0,
                             "Insufficient executable depth for requested quantity")

    spread_bps = abs(levels[0].price - best_price) / best_price * 10_000
    impact = impact_bps(best_price, vwap, side)
    latency_buffer = latency_ms / 1000.0 * short_term_vol_bps_per_s
    # Taker is certain to execute but pays taker fee + impact. Maker avoids the taker fee,
    # but fill probability is uncertain, so we only recommend it at low urgency and low impact.
    taker_cost = impact + taker_fee_bps + latency_buffer
    maker_cost = max(0.0, impact * 0.25) + maker_fee_bps + latency_buffer * 0.5

    if taker_cost > max_adverse_bps:
        order_type = "NO_TRADE"
        rationale = "Expected taker execution cost exceeds configured adverse-cost budget"
        slices = 0
    elif urgency >= 0.75:
        order_type = "MARKET"
        rationale = "High urgency favors execution certainty over maker-fee savings"
        slices = 1
    elif maker_cost + 2.0 < taker_cost and impact < max_adverse_bps * 0.5:
        order_type = "LIMIT_MAKER"
        rationale = "Low urgency and favorable modeled maker economics; fill is not guaranteed"
        slices = max(1, ceil(quantity / max(quantity / 4.0, 1e-12)))
    else:
        order_type = "IOC_LIMIT"
        rationale = "Bounded-price execution balances fill probability and price protection"
        slices = 1

    return ExecutionPlan(side, quantity, best_price, vwap, spread_bps, impact, taker_fee_bps,
                         latency_buffer, taker_cost, max_adverse_bps, order_type, slices, rationale)
