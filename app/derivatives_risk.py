from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
import math


@dataclass(frozen=True)
class DerivativesSnapshot:
    symbol: str
    funding_rate: float | None = None
    open_interest: float | None = None
    open_interest_change_pct: float | None = None
    basis_pct: float | None = None
    liquidation_notional: float | None = None
    order_flow_imbalance: float | None = None
    observed_at_ms: int | None = None


def _finite(x: float | None) -> bool:
    return x is not None and math.isfinite(float(x))


def derivatives_stress(snapshot: DerivativesSnapshot) -> dict:
    """Research/risk score only; never a directional trading signal.

    Evidence-backed inputs: funding/carry, open-interest expansion, basis,
    liquidation pressure and order-flow stress. Missing inputs are neutral and
    confidence falls. Thresholds are conservative screening defaults and must be
    calibrated on venue-specific history before live use.
    """
    components: dict[str, float] = {}
    if _finite(snapshot.funding_rate):
        # Funding is represented as a decimal per funding interval. Extreme
        # absolute funding is treated as crowding, not direction.
        components["funding_crowding"] = min(1.0, abs(float(snapshot.funding_rate)) / 0.0015)
    if _finite(snapshot.open_interest_change_pct):
        components["oi_expansion"] = min(1.0, max(0.0, abs(float(snapshot.open_interest_change_pct))) / 15.0)
    if _finite(snapshot.basis_pct):
        components["basis_stretch"] = min(1.0, abs(float(snapshot.basis_pct)) / 2.0)
    if _finite(snapshot.liquidation_notional):
        # Scale-free only when a caller supplies a normalized liquidation value.
        components["liquidation_pressure"] = min(1.0, max(0.0, float(snapshot.liquidation_notional)))
    if _finite(snapshot.order_flow_imbalance):
        components["order_flow_stress"] = min(1.0, abs(float(snapshot.order_flow_imbalance)))

    weights = {
        "funding_crowding": 0.25,
        "oi_expansion": 0.20,
        "basis_stretch": 0.20,
        "liquidation_pressure": 0.25,
        "order_flow_stress": 0.10,
    }
    total_weight = sum(weights[k] for k in components)
    score = sum(components[k] * weights[k] for k in components) / total_weight if total_weight else 0.0
    if score >= 0.75:
        state = "SEVERE"
    elif score >= 0.50:
        state = "ELEVATED"
    elif score >= 0.25:
        state = "WATCH"
    else:
        state = "NORMAL"
    return {
        "symbol": snapshot.symbol,
        "stress_score": round(float(score), 4),
        "state": state,
        "components": {k: round(float(v), 4) for k, v in components.items()},
        "observations": len(components),
        "confidence": round(len(components) / len(weights), 4),
        "execution_authority": False,
        "directional_signal": False,
        "action": "BLOCK_NEW_RISK" if state == "SEVERE" else "REDUCE_RISK" if state == "ELEVATED" else "MONITOR",
    }


def normalize_open_interest_change(previous: float | None, current: float | None) -> float | None:
    if not _finite(previous) or not _finite(current) or float(previous) <= 0:
        return None
    return (float(current) / float(previous) - 1.0) * 100.0


def basis_pct(spot: float | None, perp: float | None) -> float | None:
    if not _finite(spot) or not _finite(perp) or float(spot) <= 0:
        return None
    return (float(perp) / float(spot) - 1.0) * 100.0
