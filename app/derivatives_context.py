from __future__ import annotations
import math
from .derivatives_risk import DerivativesSnapshot, derivatives_stress, normalize_open_interest_change

async def fetch_public_derivatives_context(exchange_id: str, symbol: str) -> dict:
    """Fetch optional public funding/open-interest context through CCXT.

    Missing exchange-specific methods are treated as unavailable data, never as a
    directional signal. The risk layer may fail closed for live entries when configured.
    """
    import ccxt.async_support as ccxt
    ex_cls=getattr(ccxt,str(exchange_id).lower(),None)
    if ex_cls is None: return {"status":"UNSUPPORTED_EXCHANGE"}
    ex=ex_cls({"enableRateLimit":True,"timeout":10000})
    try:
        await ex.load_markets()
        if symbol not in ex.markets: return {"status":"SYMBOL_UNAVAILABLE"}
        funding=None; oi=None; prev_oi=None; basis=None
        if ex.has.get("fetchFundingRate"):
            try: funding=float((await ex.fetch_funding_rate(symbol)).get("fundingRate"))
            except Exception: pass
        if ex.has.get("fetchOpenInterest"):
            try:
                row=await ex.fetch_open_interest(symbol); oi=float(row.get("openInterestValue") or row.get("openInterestAmount") or row.get("openInterest"))
            except Exception: pass
        # Some exchanges expose a prior OI only through history; don't invent one.
        snap=DerivativesSnapshot(symbol=symbol,funding_rate=funding,open_interest=oi,open_interest_change_pct=normalize_open_interest_change(prev_oi,oi),observed_at_ms=ex.milliseconds())
        result=derivatives_stress(snap)
        result["status"]="OK" if result["observations"] else "UNAVAILABLE"
        return result
    finally:
        await ex.close()
