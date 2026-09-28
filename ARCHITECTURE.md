# Architecture 3.10.35

The application is deployed as three layers: Android control client, Google Cloud Run trading backend, and Supabase PostgreSQL persistence. Google Cloud Storage is used for model artifacts. Broker APIs remain external.

The Android client is not the execution engine. This prevents Android process suspension, device reboot, battery loss, or network changes from silently stopping the trading service.

Vercel is not part of this release.

## 3.10.41 Adaptive strategy layer
The adaptive stack now has four distinct responsibilities: (1) regime classification, (2) regime-conditioned strategy selection,
(3) LightGBM trade-level confirmation, and (4) deterministic execution/risk. Observed fills/outcomes are stored separately and can
influence future strategy selection only through a bounded, recency-weighted online score. The router cannot change risk limits,
custody authority, withdrawal authority, or execution permissions.


## 3.10.42 Trade Memory & Replay Engine
AtlasRisk now separates live decision-time information from post-trade learning memory. Each adaptive position lifecycle can become a TradeLearningEpisode. After the position closes, the worker can replay the same entry/exit window against alternative strategies, record MAE/MFE and regime transitions, and persist counterfactual strategy results.

The replay engine never grants execution authority and never writes future observations back into the historical decision snapshot. The live router can use only completed StrategyOutcome rows and bounded online scores.

The policy-level walk-forward validator evaluates regime detection, outcome feedback, switching hysteresis, blending and abstention together. A failed policy gate fails closed for autonomous live adaptive trading.
