# Atlas Trading OS 3.8.1 — Gemini + Groq AI Brain

- Gemini is the primary research/deeper-analysis provider.
- Groq is the fast secondary market-analysis provider.
- Both providers are called independently for auditable dual analysis.
- No Claude integration is included.
- API keys are configuration-only and must be supplied through Secret Manager/environment variables.
- AI outputs are advisory research context only; they cannot authorize orders, withdrawals, or payout release.
- Provider failures are isolated so one unavailable provider does not discard the other provider's result.
- Default models: `gemini-3.8-flash` and `openai/gpt-oss-20b`.
