from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
import math


@dataclass(frozen=True)
class ExecutorConfig:
    kind: str
    total_quantity: float
    slices: int = 1
    interval_seconds: int = 60
    max_slippage_bps: float = 25.0
    stop_loss_price: float | None = None
    take_profit_price: float | None = None


class ExecutorValidationError(ValueError):
    pass


SUPPORTED_EXECUTORS = {"POSITION", "DCA", "TWAP"}


def validate_executor_config(cfg: ExecutorConfig) -> None:
    if cfg.kind not in SUPPORTED_EXECUTORS:
        raise ExecutorValidationError("Unsupported executor type")
    if not math.isfinite(cfg.total_quantity) or cfg.total_quantity <= 0:
        raise ExecutorValidationError("Executor quantity must be positive")
    if cfg.slices < 1 or cfg.slices > 200:
        raise ExecutorValidationError("Executor slices must be between 1 and 200")
    if cfg.interval_seconds < 1 or cfg.interval_seconds > 86400:
        raise ExecutorValidationError("Executor interval is outside allowed bounds")
    if cfg.max_slippage_bps < 0 or cfg.max_slippage_bps > 500:
        raise ExecutorValidationError("Executor slippage guard is outside allowed bounds")
    if cfg.stop_loss_price is not None and cfg.stop_loss_price <= 0:
        raise ExecutorValidationError("Stop price must be positive")
    if cfg.take_profit_price is not None and cfg.take_profit_price <= 0:
        raise ExecutorValidationError("Take-profit price must be positive")


def build_executor_plan(cfg: ExecutorConfig, *, market_price: float) -> dict[str, Any]:
    validate_executor_config(cfg)
    if not math.isfinite(market_price) or market_price <= 0:
        raise ExecutorValidationError("Market price must be positive")
    slices = cfg.slices if cfg.kind in {"DCA", "TWAP"} else 1
    slice_qty = cfg.total_quantity / slices
    if slice_qty <= 0:
        raise ExecutorValidationError("Slice quantity rounded to zero")
    return {
        "kind": cfg.kind,
        "total_quantity": cfg.total_quantity,
        "slice_quantity": slice_qty,
        "slices": slices,
        "interval_seconds": cfg.interval_seconds,
        "max_slippage_bps": cfg.max_slippage_bps,
        "stop_loss_price": cfg.stop_loss_price,
        "take_profit_price": cfg.take_profit_price,
        "market_price": market_price,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_authority": True,
    }


def next_slice(plan: dict[str, Any], executed_quantity: float) -> dict[str, Any] | None:
    total = float(plan["total_quantity"])
    done = max(0.0, float(executed_quantity))
    remaining = max(0.0, total - done)
    if remaining <= 1e-12:
        return None
    qty = min(float(plan["slice_quantity"]), remaining)
    return {"quantity": qty, "remaining_after": max(0.0, remaining - qty), "slice_index": int(round(done / float(plan["slice_quantity"]))) + 1}
