from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal
import math

Side = Literal["buy", "sell"]

@dataclass(frozen=True)
class FXExecutionObservation:
    provider: str
    symbol: str
    side: Side
    quantity: float
    arrival_mid: float
    execution_price: float
    executed_quantity: float
    arrival_timestamp_ms: int
    execution_timestamp_ms: int
    fee_bps: float = 0.0
    mid_after_1s: float | None = None
    mid_after_5s: float | None = None

@dataclass(frozen=True)
class FXTCAResult:
    provider: str
    symbol: str
    side: Side
    fill_ratio: float
    implementation_shortfall_bps: float
    fee_bps: float
    net_execution_cost_bps: float
    adverse_selection_1s_bps: float | None
    adverse_selection_5s_bps: float | None
    latency_ms: int
    quality: str
    rationale: str


def _finite_positive(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _signed_move(side: Side, from_price: float, to_price: float) -> float:
    # Positive = adverse movement after our execution.
    return ((to_price - from_price) / from_price * 10_000.0) if side == "buy" else ((from_price - to_price) / from_price * 10_000.0)


def evaluate_fx_execution(obs: FXExecutionObservation) -> FXTCAResult:
    if obs.side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if not obs.provider or not obs.symbol:
        raise ValueError("provider and symbol are required")
    if obs.quantity <= 0 or obs.executed_quantity < 0 or obs.executed_quantity > obs.quantity:
        raise ValueError("invalid quantity/fill")
    _finite_positive(obs.arrival_mid, "arrival_mid")
    _finite_positive(obs.execution_price, "execution_price")
    if obs.fee_bps < 0 or obs.arrival_timestamp_ms < 0 or obs.execution_timestamp_ms < obs.arrival_timestamp_ms:
        raise ValueError("invalid fee/timestamps")

    fill_ratio = obs.executed_quantity / obs.quantity
    shortfall = _signed_move(obs.side, obs.arrival_mid, obs.execution_price)
    net_cost = shortfall + obs.fee_bps
    adv1 = None if obs.mid_after_1s is None else _signed_move(obs.side, obs.execution_price, obs.mid_after_1s)
    adv5 = None if obs.mid_after_5s is None else _signed_move(obs.side, obs.execution_price, obs.mid_after_5s)
    latency = obs.execution_timestamp_ms - obs.arrival_timestamp_ms

    if fill_ratio < 1.0:
        quality = "PARTIAL"
        rationale = "Execution did not fully fill requested quantity; investigate liquidity or routing." 
    elif net_cost < 0.5:
        quality = "GOOD"
        rationale = "Net execution cost is within the research target." 
    elif net_cost < 1.5:
        quality = "ACCEPTABLE"
        rationale = "Execution cost is measurable but remains within a moderate range." 
    else:
        quality = "POOR"
        rationale = "Net execution cost is elevated; provider/routing assumptions should be reviewed."

    return FXTCAResult(
        provider=obs.provider,
        symbol=obs.symbol,
        side=obs.side,
        fill_ratio=fill_ratio,
        implementation_shortfall_bps=shortfall,
        fee_bps=obs.fee_bps,
        net_execution_cost_bps=net_cost,
        adverse_selection_1s_bps=adv1,
        adverse_selection_5s_bps=adv5,
        latency_ms=latency,
        quality=quality,
        rationale=rationale,
    )
