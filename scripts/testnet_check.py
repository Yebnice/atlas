#!/usr/bin/env python3
"""Read-only CCXT sandbox connectivity check. It never creates an order."""
import os
import sys
from app.broker import Broker, BrokerConfig

exchange = os.getenv("DEFAULT_EXCHANGE", "bybit")
symbol = os.getenv("DEFAULT_SYMBOL", "BTC/USDT:USDT")
config = BrokerConfig(exchange, os.getenv("EXCHANGE_API_KEY", ""), os.getenv("EXCHANGE_API_SECRET", ""),
                      os.getenv("EXCHANGE_PASSWORD", ""), sandbox=True,
                      market_type=os.getenv("DEFAULT_MARKET_TYPE", "swap"), timeout_ms=10000)
b = Broker.get(config)
print("exchange:", exchange, "sandbox: true")
print("symbol:", symbol)
print("ticker:", b.ticker(symbol))
print("market limits:", b.market_info(symbol).get("limits", {}))
print("stop feature:", b.supports_feature(symbol, "stopLoss"))
