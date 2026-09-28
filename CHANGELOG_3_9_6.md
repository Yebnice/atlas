# Atlas Trading OS 3.9.6

- Added tenant-scoped Grid Bot configuration with arithmetic/geometric grids and paper-first controls.
- Added authenticated TradingView-compatible webhook endpoints with one-time secret issuance and idempotent event storage.
- Added standardized exchange connector registry for Binance, Bybit, OKX, Bitget, Kraken, Coinbase, KuCoin and Hyperliquid.
- Connector registry is capability metadata only; it does not bypass customer credential verification or live-trading gates.
- Webhook events are RECEIVED_ONLY until a strategy-specific, risk-gated action is explicitly configured.
