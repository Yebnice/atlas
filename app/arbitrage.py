from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class TriangleQuote:
    symbol: str
    bid: float
    ask: float
    bid_qty: float = 0.0
    ask_qty: float = 0.0


@dataclass(frozen=True)
class TriangleOpportunity:
    path: tuple[str, str, str]
    start_quote: float
    end_quote: float
    gross_edge_pct: float
    fees_pct: float
    slippage_buffer_pct: float
    safety_buffer_pct: float
    net_edge_pct: float
    executable: bool
    reason: str = ""


def _positive(x: float) -> bool:
    return x > 0 and x == x


def _cross(amount: float, price: float, side: str) -> float:
    if not _positive(price):
        return 0.0
    return amount * price if side == "SELL" else amount / price


def triangular_cycle(*args, **kwargs):
    raise ValueError("Use evaluate_triangle() with explicit asset continuity")


def evaluate_triangle(
    quotes: Mapping[str, TriangleQuote],
    legs: tuple[tuple[str, str, str, str], tuple[str, str, str, str], tuple[str, str, str, str]],
    start_quote: float,
    fee_rate: float,
    slippage_buffer_pct: float = 0.05,
    safety_buffer_pct: float = 0.05,
    start_asset: str = "USDT",
) -> TriangleOpportunity:
    """Evaluate a triangular cycle with explicit asset continuity and server-side costs.

    BUY consumes quote_asset and produces base_asset. SELL consumes base_asset and
    produces quote_asset. A cycle is executable only when every leg chains into the
    next and the final asset equals start_asset. Depth is checked conservatively when
    a quote supplies a non-zero top-of-book quantity.
    """
    path = tuple(x[0] for x in legs)
    if start_quote <= 0 or fee_rate < 0 or slippage_buffer_pct < 0 or safety_buffer_pct < 0:
        return TriangleOpportunity(path, start_quote, 0.0, 0.0, fee_rate * 300,
                                   slippage_buffer_pct, safety_buffer_pct, -100.0, False, "invalid_costs_or_capital")
    current_asset = start_asset.upper()
    amount = float(start_quote)
    for symbol, side, base_raw, quote_raw in legs:
        base, quote = base_raw.upper(), quote_raw.upper()
        if side not in {"BUY", "SELL"}:
            return TriangleOpportunity(path, start_quote, 0.0, 0.0, fee_rate * 300,
                                       slippage_buffer_pct, safety_buffer_pct, -100.0, False, "invalid_side")
        expected_input = quote if side == "BUY" else base
        output_asset = base if side == "BUY" else quote
        if current_asset != expected_input:
            return TriangleOpportunity(path, start_quote, 0.0, 0.0, fee_rate * 300,
                                       slippage_buffer_pct, safety_buffer_pct, -100.0, False, "asset_chain_mismatch")
        q = quotes.get(symbol)
        if q is None:
            return TriangleOpportunity(path, start_quote, 0.0, 0.0, fee_rate * 300,
                                       slippage_buffer_pct, safety_buffer_pct, -100.0, False, "missing_quote")
        px = q.ask if side == "BUY" else q.bid
        top_qty = q.ask_qty if side == "BUY" else q.bid_qty
        if not _positive(px):
            return TriangleOpportunity(path, start_quote, 0.0, 0.0, fee_rate * 300,
                                       slippage_buffer_pct, safety_buffer_pct, -100.0, False, "invalid_price")
        required_qty = amount / px if side == "BUY" else amount
        if top_qty > 0 and required_qty > top_qty:
            return TriangleOpportunity(path, start_quote, 0.0, 0.0, fee_rate * 300,
                                       slippage_buffer_pct, safety_buffer_pct, -100.0, False, "insufficient_top_of_book_depth")
        amount = _cross(amount, px, side) * (1.0 - fee_rate)
        current_asset = output_asset
    if current_asset != start_asset.upper():
        return TriangleOpportunity(path, start_quote, 0.0, 0.0, fee_rate * 300,
                                   slippage_buffer_pct, safety_buffer_pct, -100.0, False, "cycle_does_not_close")
    gross = ((amount / start_quote) - 1.0) * 100.0
    fees_pct = fee_rate * 3.0 * 100.0
    net = gross - slippage_buffer_pct - safety_buffer_pct
    return TriangleOpportunity(path, start_quote, amount, gross, fees_pct,
                               slippage_buffer_pct, safety_buffer_pct, net, net > 0,
                               "net_edge_positive" if net > 0 else "net_edge_non_positive")
