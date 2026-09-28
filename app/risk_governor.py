from __future__ import annotations
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class RiskGovernorDecision:
    action: str
    reasons: tuple[str, ...]
    execution_authority: bool = False


def evaluate_trade(*, side: str, price: float, quantity: float, live: bool,
                   stop_loss_price: float | None, take_profit_price: float | None,
                   signal: dict, spread_bps: float | None = None,
                   max_spread_bps: float = 100.0, equity: float | None = None,
                   risk_per_trade: float | None = None, risk_tolerance: float = 0.0) -> RiskGovernorDecision:
    reasons=[]
    if side not in {"buy","sell"}: reasons.append("invalid_side")
    if not math.isfinite(price) or price <= 0 or not math.isfinite(quantity) or quantity <= 0: reasons.append("invalid_market_or_quantity")
    if live and not stop_loss_price: reasons.append("live_protective_stop_missing")
    if live and stop_loss_price is not None:
        if (side=="buy" and stop_loss_price>=price) or (side=="sell" and stop_loss_price<=price): reasons.append("protective_stop_wrong_side")
    if take_profit_price is not None:
        if (side=="buy" and take_profit_price<=price) or (side=="sell" and take_profit_price>=price): reasons.append("take_profit_wrong_side")
    # Position size must be derived from the distance to the protective stop, not
    # from notional alone. This is the core discipline rule for risk-per-trade sizing.
    if equity is not None and risk_per_trade is not None and stop_loss_price is not None and equity > 0 and risk_per_trade > 0:
        risk_cash = abs(price - stop_loss_price) * quantity
        allowed = equity * risk_per_trade * (1.0 + max(0.0, risk_tolerance))
        if not math.isfinite(risk_cash) or risk_cash > allowed + 1e-9:
            reasons.append("risk_per_trade_limit")
    if spread_bps is not None and (not math.isfinite(spread_bps) or spread_bps < 0 or spread_bps > max_spread_bps): reasons.append("spread_guard")
    data_quality=(signal.get("data_quality") or {}) if isinstance(signal,dict) else {}
    if data_quality.get("valid") is False: reasons.append("market_data_quality")
    if reasons: return RiskGovernorDecision("BLOCK",tuple(reasons),False)
    return RiskGovernorDecision("ALLOW",tuple(),False)
