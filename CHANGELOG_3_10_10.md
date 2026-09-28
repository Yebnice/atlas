# Atlas 3.10.10 — OANDA Practice Demo Hardening

- Fact-checked against OANDA v20 Practice REST/stream documentation.
- Added practice-only preflight and read-only price endpoints.
- Added quote freshness and tradeability validation.
- Added configurable demo order-size cap.
- Added explicit practice-only demo execution checks.
- Added OANDA practice streaming URL helper.
- No production/live OANDA path was enabled by this release.


## OANDA v20 repository alignment
- Direct client-order lookup using OANDA OrderSpecifier `@clientOrderID`.
- Incremental transaction reconciliation via `transactions/sinceid`.
- Transaction stream URL and JSON-lines parser for durable account event processing.
- Retained Practice-only demo gate and server-side credentials.
