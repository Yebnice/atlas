# Grid, TradingView Webhooks and Exchange Connectors

## Grid
Grid creation is paper-first. The engine supports arithmetic and geometric price levels and stores the complete grid per customer trading account. Live execution must pass the existing exchange/account/risk/protective-order gates.

## TradingView webhooks
Create a customer webhook, copy the one-time token, and configure TradingView to POST JSON to `/api/webhooks/{endpoint_id}` with the secret sent in the `X-Atlas-Webhook-Token` header. Atlas stores only a SHA-256 token hash. Webhook events are idempotent and are received-only by default.

TradingView recommends secure authenticated webhook endpoints and warns not to put passwords or other sensitive information in webhook payloads. Webhooks may fail to reach a destination and TradingView cancels requests that take longer than three seconds, so the endpoint is intentionally fast and asynchronous. See official TradingView webhook documentation.

## Exchange connector registry
The registry standardizes supported venue capabilities without storing API secrets. Customer API credentials remain subject to the existing isolated-account and Secret Manager architecture. The initial registry covers Binance, Bybit, OKX, Bitget, Kraken, Coinbase, KuCoin and Hyperliquid.
