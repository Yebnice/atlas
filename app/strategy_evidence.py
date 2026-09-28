"""Evidence and scope notes for Atlas strategy components.

These notes distinguish research-supported strategy *classes* from commonly used
indicators and heuristic combinations. They are not claims of profitability.
"""

STRATEGY_EVIDENCE = {
    "trend": {
        "class": "TIME_SERIES_TREND",
        "evidence_level": "ESTABLISHED_RESEARCH_CLASS",
        "note": "Trend-following/time-series momentum has published long-horizon, cross-asset evidence; results are regime-dependent and can suffer sharp drawdowns.",
        "sources": [
            "Moskowitz, Ooi & Pedersen (2012), Time Series Momentum, Journal of Financial Economics 104(2):228-250.",
            "Hurst, Ooi & Pedersen (2017), A Century of Evidence on Trend-Following Investing, Journal of Portfolio Management.",
        ],
    },
    "momentum": {
        "class": "TIME_SERIES_MOMENTUM",
        "evidence_level": "ESTABLISHED_RESEARCH_CLASS",
        "note": "Time-series momentum is supported by published evidence across liquid futures/asset classes, but implementation choices and costs matter.",
        "sources": [
            "Moskowitz, Ooi & Pedersen (2012), Time Series Momentum, Journal of Financial Economics 104(2):228-250.",
            "Hurst, Ooi & Pedersen (2017), A Century of Evidence on Trend-Following Investing, Journal of Portfolio Management.",
        ],
    },
    "breakout": {
        "class": "PRICE_CHANNEL_BREAKOUT",
        "evidence_level": "ESTABLISHED_TRADING_RULE_CLASS",
        "note": "Prior-high/low channel breakouts are a classical trend-following construction; the app does not treat a chosen lookback as universally optimal.",
        "sources": [
            "Donchian-style price-channel breakout methodology; evaluated here only through forward/out-of-sample research gates.",
            "Moskowitz, Ooi & Pedersen (2012), Time Series Momentum.",
        ],
    },
    "mean_reversion": {
        "class": "MEAN_REVERSION",
        "evidence_level": "CONTEXT_DEPENDENT",
        "note": "Z-score mean reversion is a standard statistical construction, but profitability is highly dependent on asset, horizon, costs and regime; Atlas filters it when trend strength is high.",
        "sources": [
            "Statistical mean-reversion methodology; no standalone profitability claim is made by Atlas.",
        ],
    },
    "ensemble": {
        "class": "MULTI_FACTOR_HEURISTIC",
        "evidence_level": "EXPERIMENTAL_COMBINATION",
        "note": "The ensemble weights are engineering heuristics, not independently established alpha coefficients; Atlas therefore applies cost, out-of-sample and multiple-testing checks.",
        "sources": [
            "White (2000), A Reality Check for Data Snooping, Econometrica 68(5):1097-1126.",
        ],
    },
}

INDICATOR_NOTES = {
    "rsi": "Wilder (1978) introduced RSI; the default 14-period convention is historical, not a guarantee of predictive power.",
    "atr": "Wilder (1978) introduced Average True Range; Atlas uses it for volatility/risk levels rather than as a standalone alpha claim.",
    "adx": "Wilder (1978) introduced ADX; Atlas uses it as a trend-strength/context feature, not proof of direction.",
    "macd": "MACD is a widely used momentum/trend indicator (Appel); Atlas treats it as a confirmation feature, not standalone evidence of alpha.",
    "vwap": "VWAP is primarily an execution/benchmark concept. Atlas only computes session VWAP when meaningful volume is supplied and does not rely on it as standalone alpha.",
}


def evidence_for(name: str) -> dict:
    return dict(STRATEGY_EVIDENCE.get(name, {
        "class": "UNCLASSIFIED",
        "evidence_level": "UNVERIFIED",
        "note": "No established evidence classification is assigned.",
        "sources": [],
    }))
