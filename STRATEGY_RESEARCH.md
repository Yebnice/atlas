# Strategy Research Loop

Atlas now follows this sequence:

1. **Collect market history** for the selected asset, symbol, exchange and timeframe.
2. **Backtest every registered strategy** using lagged execution and explicit transaction costs/slippage.
3. **Run AI walk-forward validation** where sufficient history exists.
4. **Analyze regime** (trend direction/strength and realized volatility).
5. **AI-assisted review** summarizes the evidence, limitations and current market context.
6. **Promotion gate** selects strategies meeting minimum historical risk/return evidence.
7. **Paper/shadow testing** produces live signals only for promoted candidates.
8. **Production promotion** remains a separate, manual risk-controlled decision.

## Important

The research score is an internal screening metric, not a promise of profitability. Historical performance can fail out of sample. Paper/shadow results must be monitored across multiple market regimes before any strategy is considered for controlled production deployment.
