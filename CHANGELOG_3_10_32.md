# Atlas 3.10.32

- Added Strategy Lab candidate lifecycle: draft -> backtest/OOS validation -> explicit live approval.
- Added persistent Position/DCA/TWAP executor state with distributed controller and customer isolation.
- Added explicit per-executor live approval; executors never inherit global live mode implicitly.
- Fixed customer FX/commodity execution to require the verified customer OANDA account; no platform credential fallback.
- Added customer-scoped multi-asset execution routing and preserved broker-specific precision/risk gates.
- Removed the unimplemented Grid executor from the production executor API rather than falsely presenting a one-shot order as a grid.
