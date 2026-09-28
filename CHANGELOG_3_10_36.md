# 3.10.36 - Experiment tracking, drift monitoring, AI strategy creation fixes

## P0 bugfix
- **Adaptive bots crash-looped after their first promoted model.** `ensure_adaptive_model`
  stored `features` in champion metadata as `len(FEATURE_COLUMNS)` (an int). `model_is_fresh`
  then evaluated `list(24 or [])` -> `TypeError: 'int' object is not iterable` on every
  freshness check. The exception surfaced as a controller cycle failure and, after 3
  consecutive failures, the bot set itself to `STOPPED`. Now stores the column list.
  Champions already written by the old code (int on disk) are now treated as stale by
  `model_is_fresh` instead of raising, so they self-heal on the next retrain.

## Model drift monitoring
- Champion metadata now stores a feature-distribution baseline; every `ensure_adaptive_model`
  call (fresh / promoted / rejected) returns `feature_drift` (PSI vs the champion baseline).
- Deliberately restricted to short-window features and driven by **mean** PSI. Full-feature or
  max-PSI variants were tested and produced ALERT on 100% of no-drift synthetic trials
  (long rolling windows are autocorrelated; a short sample is not independent draws).
  Final design: 0/20 false ALERTs without drift, 10/10 detections with an injected
  volatility-regime shift (synthetic data - re-tune thresholds on real market history).
- `ALERT` writes audit event `MODEL_FEATURE_DRIFT_ALERT`; customer UI shows drift status.
- Not included: live-PnL vs backtest divergence (needs per-bot/per-model-version trade
  attribution that does not exist yet).

## Experiment tracking (migration 0031)
- `model_experiments`: every retrain attempt (promoted/rejected) and WARN/ALERT drift reading.
  `GET /api/admin/model-experiments`.
- `research_runs`: each daily research run per symbol with a real drift comparison vs the
  previous run (regime / top strategy / Sharpe / drawdown flags). `GET /api/research/runs`.
  The daily brief's "compare against the previous run" instruction is now actually possible.
- `strategy_candidate_runs`: every validate attempt kept (previously overwritten).
  `GET /api/customer/strategy-lab/candidates/{id}/runs` returns deltas vs previous attempt.

## AI strategy creation
- `POST /api/customer/strategy-builder` was a dead end (created a `StrategyDraft` nothing
  could validate). It now creates a Strategy Lab candidate; legacy drafts can be rescued via
  `POST /api/customer/strategy-builder/{id}/promote`.
- UI shows readable validation summaries instead of raw JSON, a History button per
  candidate, and the top panel now runs create -> validate in one step.

## Scope docs
- `SCOPE_MARKETPLACE_AND_VISUAL_BUILDER_3_10_36.md` (design only; not implemented).

## Upgrade notes
1. Run `alembic upgrade head` (adds 0031).
2. Existing champions have no drift baseline -> `NO_BASELINE` until their next promotion.

## Test coverage / limitations
- New tests: `tests/test_experiment_tracking_drift_3_10_36.py`. One existing assertion in
  `tests/test_strategy_ai.py` was updated to follow the builder's new delegation.
- The build environment lacked pytest/pydantic/httpx/lightgbm and network, so the full suite
  was NOT run end to end. Verified: drift math and freshness fix by execution (lightgbm
  stubbed), pure research-drift helpers, source-level assertions, and syntax of all touched
  files. Not verified: migration against a real DB, the new endpoints under FastAPI, the UI
  in a browser, end-to-end training/promotion with real LightGBM. Run the suite in CI first.
