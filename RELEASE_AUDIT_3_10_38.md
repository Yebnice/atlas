# AtlasRisk 3.10.38 Release Audit

## Live-money gate
This release is a hardened review build. It is **not** certified for live customer money until the external PostgreSQL/pytest/security verification is executed.

### P0
1. Fresh PostgreSQL migration — code repair included; runtime verification pending.
2. Alembic revision-width repair — included in 0001 + 0033; runtime verification pending.
3. PostgreSQL concurrency — DB timeouts and distributed locks hardened; concurrency drill pending.
4. Model drift ALERT — live entry hard stop implemented.
5. Strategy OOS promotion — fold-level gate implemented.
6. OANDA/Deriv capability validation — Deriv trade scope required; OANDA provider token/account capability recorded and execution remains provider-authoritative.
7. External immutable audit — structured external audit copy + locked Cloud Logging deployment script; cloud configuration pending.
8. FK validation — validation script included; orphan cleanup/runtime validation pending.
9. Withdrawal/fraud simulation — attack-path tests added at application layer; full integrated simulation pending.
10. Exchange failure/reconciliation — UNKNOWN semantics retained; integrated failure drills pending.

### P1
11. Versioned encryption key rotation — implemented.
12. Layered rate limiting — implemented.
13. Correlation/concentration risk — implemented with conservative risk buckets.
14. External custody signer/MPC — signer boundary implemented; real signer service remains an external dependency.
15. Live-vs-paper drift — model feature drift hard stop implemented; execution drift monitoring remains a runtime verification task.
16. Incidents — first-class incident table/helper implemented.
17. Model rollback/fencing — champion backup + risk-officer rollback + integrity gate implemented.
18. Worker failover — Redis lease refresh helper added; multi-worker failure drill pending.

### P2
19. Meta-labeling — implemented as a secondary take/skip gate.
20. Funding/OI/liquidation — public funding/OI context integrated where exchange supports it; liquidation/order-flow feeds remain venue-specific and are not invented.
21. Multi-timeframe regime — 4H/1H/15M/5M confirmation integrated for 5m/15m crypto bots.
22. Monte Carlo robustness — research output added.
23. Parameter plateau — research output added around signal-threshold variants.
24. Strategy attribution — existing research/audit records retained; deeper post-trade attribution remains a later research enhancement.

## Important
No claim of a guaranteed winning rate is made. The bot is evaluated by OOS expectancy, drawdown, profit factor, cost sensitivity, robustness and regime behavior rather than win rate alone.
