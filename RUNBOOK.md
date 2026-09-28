# Operations runbook

## Emergency stop
Call `POST /api/risk/kill`. The local kill switch is set before broker cancellation is attempted. The endpoint then attempts to cancel open orders. If cancellation fails, the system remains HALTED and the broker account must be checked manually.

## Broker timeout / UNKNOWN order
Do not resubmit the same logical trade. Call `POST /api/reconcile` for the exchange and symbol. The system intentionally leaves an unresolved order in UNKNOWN state when it cannot prove whether the exchange accepted the request.

## Restart after outage
1. Keep live trading disabled.
2. Start the application and verify `/readyz`.
3. Reconcile open/unknown orders.
4. Verify broker positions and account equity.
5. Review audit logs.
6. Re-enable live trading only after the explicit live gate is satisfied.

## Model incident
Disable live trading, preserve the model artifact and metadata, run the AI walk-forward backtest, inspect validation metrics and feature/data quality, then retrain and promote only a validated artifact.
