# Atlas 3.10.8 — FX Multi-Liquidity Execution Research

- Added research-only multi-liquidity-provider FX quote router.
- Rejects stale, mismatched, insufficient-depth and over-budget quotes.
- Models spread, taker fee and latency buffer.
- Explicitly has no execution authority.
- Adds endpoint `POST /api/research/fx-execution-route`.
- Keeps FX execution separate from Binance/CLOB assumptions.
