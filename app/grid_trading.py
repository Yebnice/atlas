from dataclasses import dataclass


@dataclass(frozen=True)
class GridLevel:
    index: int
    price: float


def build_grid(lower: float, upper: float, levels: int, arithmetic: bool = False) -> list[GridLevel]:
    if lower <= 0 or upper <= lower or levels < 2:
        raise ValueError("Invalid grid bounds")
    if arithmetic:
        step = (upper - lower) / levels
        return [GridLevel(i, lower + step * i) for i in range(levels + 1)]
    ratio = (upper / lower) ** (1.0 / levels)
    return [GridLevel(i, lower * (ratio ** i)) for i in range(levels + 1)]


def grid_profit_pct(lower: float, upper: float, levels: int, arithmetic: bool = False) -> float:
    levels_out = build_grid(lower, upper, levels, arithmetic)
    if len(levels_out) < 2:
        return 0.0
    return (levels_out[1].price / levels_out[0].price - 1.0) * 100.0
