#!/usr/bin/env python3
"""Read-only OANDA v20 practice-account connectivity check. Never places an order."""
import os
from app.forex_oanda import OandaBroker, OandaConfig

account = os.getenv("OANDA_ACCOUNT_ID", "")
token = os.getenv("OANDA_API_TOKEN", "")
if not account or not token:
    raise SystemExit("Set OANDA_ACCOUNT_ID and OANDA_API_TOKEN first")
if os.getenv("OANDA_PRACTICE", "true").lower() != "true":
    raise SystemExit("Refusing to run: OANDA_PRACTICE must be true for this demo check")
instrument = os.getenv("FOREX_SYMBOL", "EUR_USD")
b = OandaBroker(OandaConfig(account, token, True, float(os.getenv("OANDA_TIMEOUT_SECONDS", "10"))))
try:
    acct = b.account()["account"]
    print("environment: practice")
    print("account:", acct.get("id"))
    print("currency:", acct.get("currency"))
    print("NAV:", acct.get("NAV"))
    print("marginAvailable:", acct.get("marginAvailable"))
    print("quote:", b.ticker(instrument))
    print("instrument:", {k: b.market_info(instrument).get(k) for k in ("name", "displayName", "pipLocation", "tradeUnitsPrecision")})
finally:
    b.close()
