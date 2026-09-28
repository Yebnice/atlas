from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_ENVIRONMENTS = {"development", "staging", "production", "test"}


class Settings(BaseSettings):
    app_name: str = "AI Trading Console"
    app_version: str = "3.10.45"
    # No default: the previous default of "development" silently matched the also-default
    # SQLite/plaintext-fallback posture, so a deployment that simply forgot to set ENVIRONMENT
    # got the insecure combination with no warning. Requiring an explicit value means a missing
    # or misconfigured ENVIRONMENT fails app startup instead of failing open. Local/dev workflows
    # already set this via `.env` (see .env.example); CI sets it explicitly too.
    environment: str
    database_url: str = "sqlite+aiosqlite:///./data/trading.db"
    secret_key: str = ""
    app_encryption_key: str = ""  # legacy/default Fernet key; production value belongs in Secret Manager
    # Versioned encryption keys. JSON object: {"v1":"<fernet>","v2":"<fernet>"};
    # active key is used for new writes while older ciphertext remains decryptable.
    app_encryption_keys_json: str = ""
    app_encryption_active_key_id: str = "v1"
    admin_token: str = ""
    docs_enabled: bool = False

    # Customer authentication and funding. Supabase Auth is authoritative for customer identity.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwks_url: str = ""
    supabase_auth_audience: str = "authenticated"
    funding_webhook_secret: str = ""

    # Real USDT funding (TRON / TRC-20). Production API receives only a public
    # account-level extended public key (xpub) for new deposit-address derivation.
    # Private seeds never belong in the API runtime.
    usdt_tron_enabled: bool = False
    usdt_tron_network: str = "mainnet"
    usdt_tron_account_xpub: str = ""
    usdt_trongrid_base_url: str = "https://api.trongrid.io"
    usdt_trongrid_api_key: str = ""
    usdt_tron_usdt_contract: str = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    # Public treasury/collection address. Customer attribution uses unique virtual deposit addresses;
    # this address is for controlled sweeps/treasury accounting, not direct customer attribution.
    usdt_tron_treasury_address: str = "TWFuigmmGbb5gsTS4KUtY5v2FmA1rJ3yC5"
    usdt_tron_shared_deposit_mode: bool = False  # never guess customer from amount on a shared TRC-20 address
    customer_cash_only_trading: bool = True
    usdt_tron_poll_seconds: int = 60
    usdt_tron_min_confirmations: int = 19
    usdt_tron_scan_pages: int = 10
    usdt_tron_cursor_overlap_seconds: int = 120
    usdt_tron_verify_receipt: bool = True
    usdt_tron_sweep_enabled: bool = False
    usdt_tron_sweep_min_confirmations: int = 19
    usdt_tron_sweep_min_amount: float = 1.0
    usdt_tron_sweep_keep_trx: float = 5.0

    default_asset: str = "crypto"
    default_symbol: str = "BTC/USDT:USDT"
    default_exchange: str = "bybit"
    default_timeframe: str = "1h"
    default_market_type: str = "swap"

    # Forex / learning broker (OANDA v20). OANDA is permanently DEMO/PRACTICE-ONLY in AtlasRisk.
    # Live OANDA trading is intentionally not supported; forex_live_enabled is retained only for
    # backward-compatible configuration parsing and is rejected at startup if enabled.
    forex_broker: str = "oanda"
    oanda_account_id: str = ""
    oanda_api_token: str = ""
    oanda_practice: bool = True
    forex_demo_enabled: bool = False
    forex_live_enabled: bool = False
    oanda_timeout_seconds: float = 10.0
    oanda_demo_max_units: float = 100000.0
    oanda_demo_max_quote_age_seconds: float = 3.0
    # Deriv v3 real-account adapter. Token belongs in Secret Manager; live is fail-closed.
    deriv_app_id: int = 0
    deriv_api_token: str = ""
    deriv_account_id: str = ""
    deriv_live_enabled: bool = False
    deriv_timeout_seconds: float = 10.0


    # Live execution is fail-closed by default.
    paper_trading: bool = True
    live_trading_enabled: bool = False
    customer_live_trading_enabled: bool = False  # Requires an isolated exchange/subaccount mapping per customer.
    binance_customer_subaccounts_enabled: bool = True
    binance_customer_universal_transfer_allowed: bool = False
    broker_sandbox: bool = True
    require_live_confirmation: bool = True
    live_confirmation_text: str = "ENABLE_LIVE_TRADING"
    require_single_worker_for_live: bool = True
    # Daily autonomous market intelligence + research cycle.
    daily_research_enabled: bool = True
    daily_research_hour_utc: int = 1
    daily_research_minute_utc: int = 30
    daily_research_lock_seconds: int = 3600
    research_symbols: str = "SPY,QQQ,BTC-USD,ETH-USD,EURUSD=X,GC=F,CL=F"
    research_yahoo_period: str = "3y"
    research_taker_bps: float = 5.5
    research_slippage_bps: float = 2.0
    research_folds: int = 5
    research_min_train: int = 800
    research_ai_threshold: float = 0.05
    # Adaptive AI bot: models retrain automatically but only become champion after OOS gates.
    adaptive_ai_enabled: bool = True
    adaptive_retrain_hours: float = 24.0
    adaptive_min_sharpe: float = 0.50
    adaptive_max_drawdown: float = -0.25
    adaptive_min_trades: int = 20
    adaptive_min_total_return: float = 0.0
    research_min_oos_total_return: float = 0.0
    research_min_oos_positive_fold_ratio: float = 0.50
    adaptive_min_quote_volume_24h_usd: float = 5_000_000.0
    adaptive_require_established_crypto: bool = True
    adaptive_bot_controller_enabled: bool = True
    adaptive_bot_poll_seconds: int = 30
    adaptive_bot_default_interval_seconds: int = 900
    adaptive_established_symbols: str = "BTC/USDT:USDT,ETH/USDT:USDT,BNB/USDT:USDT,SOL/USDT:USDT,XRP/USDT:USDT,ADA/USDT:USDT,DOGE/USDT:USDT"
    adaptive_established_fx_symbols: str = "EUR_USD,GBP_USD,USD_JPY,USD_CHF,AUD_USD,USD_CAD,NZD_USD"
    adaptive_established_commodity_symbols: str = "XAU_USD,XAG_USD,WTICO_USD,BCO_USD,NATGAS_USD"
    adaptive_require_established_noncrypto: bool = True
    adaptive_strategy_router_enabled: bool = True
    adaptive_strategy_switch_min_advantage: float = 0.15
    adaptive_strategy_switch_cooldown_minutes: int = 180
    adaptive_strategy_min_regime_bars: int = 3
    adaptive_strategy_min_trades: int = 20
    adaptive_strategy_online_weight: float = 0.25
    adaptive_strategy_online_min_observations: int = 10
    adaptive_strategy_online_half_life_days: float = 14.0
    adaptive_strategy_blend_enabled: bool = True
    adaptive_strategy_blend_top_n: int = 3
    adaptive_strategy_cost_bps: float = 7.5
    adaptive_strategy_router_folds: int = 5
    adaptive_strategy_router_min_train: int = 800
    adaptive_strategy_router_required_positive_fold_ratio: float = 0.50
    adaptive_strategy_policy_validation_stride_bars: int = 4
    # Post-trade market memory / counterfactual replay. These jobs are research-only and
    # never grant live execution authority. Completed episodes are replayed against future
    # bars only after the real trade has closed.
    trade_learning_enabled: bool = True
    trade_learning_poll_seconds: int = 120
    trade_learning_max_episodes_per_cycle: int = 10
    trade_learning_lookback_days: int = 365
    alpha_vantage_api_key: str = ""
    market_intelligence_enabled: bool = True
    market_intelligence_timeout_seconds: float = 8.0
    market_intelligence_max_news_items: int = 60
    # AI research providers. Keys belong in Secret Manager / environment only.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_strategy_model: str = "gemini-2.5-pro"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_strategy_model: str = "openai/gpt-oss-20b"
    groq_max_completion_tokens: int = 2048

    # Withdrawal approval/execution controls. Fund release is fail-closed unless explicitly configured.
    withdrawals_enabled: bool = True
    withdrawal_dual_approval: bool = True
    withdrawal_max_amount: float = 5000.0
    withdrawal_high_risk_threshold: float = 0.75
    # Comma-separated id:token pairs, e.g. "finance-01:secret,finance-02:secret".
    withdrawal_approver_tokens: str = ""
    payout_provider: str = "disabled"  # disabled | external_signer | bank_http | ccxt (ccxt is non-production only)
    payout_live_enabled: bool = False
    payout_require_reconciliation: bool = True
    withdrawal_release_tokens: str = ""  # release-operator id:token pairs
    withdrawal_whitelist_enabled: bool = True
    withdrawal_destination_fingerprints: str = ""  # sha256(currency|network|destination), comma-separated
    local_signing_enabled: bool = False
    local_signing_public_key: str = ""  # Ed25519 public key PEM; private key never belongs on the server
    bank_payout_url: str = ""
    bank_status_url_template: str = ""
    bank_status_by_idempotency_url_template: str = ""
    bank_payout_hmac_secret: str = ""
    bank_payout_timeout_seconds: int = 15

    # Risk controls.
    initial_equity: float = 10_000.0
    max_drawdown: float = 0.15
    daily_loss_limit: float = 0.03
    max_leverage: float = 3.0
    risk_per_trade: float = 0.005
    max_notional_usd: float = 10_000.0
    max_position_notional_usd: float = 10_000.0
    max_total_exposure_usd: float = 20_000.0
    max_open_positions: int = 3
    max_slippage_bps: float = 30.0
    stale_data_minutes: int = 180
    max_signal_age_seconds: int = 7_200
    stop_loss_pct: float = 0.01
    take_profit_pct: float = 0.02
    require_protective_stop_for_live: bool = True
    # Trading-discipline controls. These are deliberately deterministic and apply
    # before an order is created; they are not predictions and cannot be overridden by AI.
    discipline_enabled: bool = True
    discipline_max_entries_per_day: int = 20
    discipline_entry_cooldown_seconds: int = 900
    discipline_enforce_risk_per_trade: bool = True
    discipline_risk_tolerance: float = 0.10

    # Research-backed multi-strategy engine. Paper-first and independently testable.
    strategy_engine_enabled: bool = True
    strategy_signal_threshold: float = 0.20
    strategy_target_vol_annual: float = 0.15
    strategy_max_leverage: float = 1.5
    strategy_stop_atr: float = 2.5
    strategy_take_profit_atr: float = 4.0

    # Market-data quality controls.
    min_signal_score: float = 0.05
    min_bars: int = 250
    max_data_gap_bars: int = 3
    # Research protections inspired by robust forward-testing practice.
    strategy_drawdown_halt: float = 0.10
    strategy_daily_loss_halt: float = 0.03
    strategy_stoploss_guard_trades: int = 3
    strategy_stoploss_guard_bars: int = 24
    strategy_volatility_cap_annual: float = 1.50

    exchange_api_key: str = ""
    exchange_api_secret: str = ""
    exchange_password: str = ""
    exchange_timeout_ms: int = 10_000

    log_level: str = "INFO"
    metrics_enabled: bool = True
    background_reconciliation_enabled: bool = True
    reconciliation_interval_seconds: int = 60
    # API abuse/resource controls. Per-process limiter; put a gateway limiter in front for multi-worker deployments.
    api_rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10
    otp_rate_limit_per_minute: int = 5
    withdrawal_step_up_minutes: int = 10
    # Customer TOTP MFA. Uses Supabase Auth native TOTP (Google Authenticator compatible).
    customer_totp_required: bool = True
    # Admin authentication uses Supabase Auth with mandatory TOTP (Google Authenticator compatible).
    admin_totp_required: bool = True
    admin_supabase_user_ids: str = ""  # comma-separated Supabase auth user UUIDs allowed to access admin APIs
    # Server-side admin RBAC. Format: user_uuid:ROLE,user_uuid:ROLE. Database assignments take precedence.
    admin_role_assignments: str = ""
    process_role: str = "api"  # api | worker | job
    withdrawal_address_cooling_off_hours: int = 24
    withdrawal_new_address_requires_verification: bool = True
    expensive_api_rate_limit_per_minute: int = 12
    metrics_require_admin: bool = True

    # Commercial plans / subscriptions / referrals. Payment provider secrets belong in Secret Manager.
    billing_enabled: bool = True
    billing_currency: str = "USD"
    billing_trial_days: int = 7
    billing_referral_discount_pct: float = 5.0
    billing_referral_commission_pct: float = 1.0
    billing_referral_payout_delay_days: int = 45
    billing_referral_min_payout: float = 25.0
    stripe_enabled: bool = False
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter_monthly: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_elite_monthly: str = ""
    stripe_price_starter_annual: str = ""
    stripe_price_pro_annual: str = ""
    stripe_price_elite_annual: str = ""
    stripe_referral_coupon_id: str = ""

    # 3.4 distributed controls. Redis is required in production for cross-instance rate limiting.
    redis_url: str = ""
    distributed_rate_limit_required: bool = True
    withdrawal_velocity_24h: float = 10000.0
    withdrawal_velocity_7d: float = 25000.0
    withdrawal_balance_ratio_review: float = 0.50
    withdrawal_balance_ratio_block: float = 0.90
    withdrawal_review_score: float = 0.55
    withdrawal_block_score: float = 0.85
    withdrawal_max_unknown_24h: int = 2
    recovery_poll_seconds: int = 30
    heartbeat_interval_seconds: int = 15
    stale_instance_seconds: int = 60
    require_backup_recovery_config: bool = True
    backup_recovery_url: str = ""
    # External security-audit copy. Cloud Run/Compute Engine should route stdout to a
    # locked Cloud Logging bucket with retention; this flag makes the application emit
    # a second structured security-audit record outside PostgreSQL.
    external_security_audit_enabled: bool = True
    external_security_audit_required: bool = True
    # Model safety / promotion controls.
    model_drift_alert_blocks_live: bool = True
    model_require_feature_baseline_for_live: bool = True
    model_integrity_required_for_live: bool = True
    model_rollback_enabled: bool = True
    strategy_oos_min_folds: int = 5
    strategy_oos_max_negative_fold_return: float = -0.20
    strategy_oos_require_last_fold_positive: bool = True
    strategy_oos_min_sharpe: float = 0.50
    strategy_oos_max_drawdown: float = -0.25
    strategy_oos_min_trades: int = 20
    meta_labeling_enabled: bool = True
    meta_label_probability_threshold: float = 0.55
    meta_label_horizon_bars: int = 3
    meta_label_min_edge_bps: float = 10.0
    derivatives_risk_enabled: bool = True
    derivatives_risk_fail_closed_live: bool = True
    derivatives_elevated_size_multiplier: float = 0.50
    # Portfolio correlation/concentration safety. These are conservative beta buckets,
    # not claimed statistical correlations; real correlation can be supplied by the
    # research layer when available.
    correlation_risk_enabled: bool = True
    correlation_group_cap_usd: float = 12000.0
    # Custody signer boundary. If enabled, local/API exchange withdrawal signing is blocked
    # unless an external signer integration is explicitly configured.
    external_custody_signer_required: bool = True
    external_custody_signer_url: str = ""
    external_custody_signer_hmac_secret: str = ""

    model_dir: str = "models"
    model_staging_dir: str = "model-staging"
    model_signing_key: str = ""  # legacy HMAC signing key; compatibility only, do not use for new deployments
    model_signing_private_key: str = ""  # Ed25519 PEM; worker/promotion process only
    model_signing_public_key: str = ""   # Ed25519 PEM; API verification only
    forwarded_allow_ips: str = ""

    # Arbitrage research/paper engine; live execution remains disabled.
    arbitrage_enabled: bool = True
    arbitrage_exchange: str = "binance"
    arbitrage_fee_rate: float = 0.001
    arbitrage_min_net_edge_pct: float = 0.10
    arbitrage_slippage_buffer_pct: float = 0.05
    arbitrage_safety_buffer_pct: float = 0.05
    arbitrage_max_capital_usdt: float = 1000.0
    # Binance triangular arbitrage live adapter. Non-atomic by nature; keep disabled until operational controls are proven.
    binance_arbitrage_live_enabled: bool = False
    binance_arbitrage_sandbox: bool = True
    binance_arbitrage_max_quote_age_ms: int = 750
    binance_arbitrage_min_net_edge_pct: float = 0.10



    @field_validator("forwarded_allow_ips")
    @classmethod
    def _validate_forwarded_allow_ips(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return value
        import ipaddress
        items = [x.strip() for x in value.split(",") if x.strip()]
        if "*" in items:
            raise ValueError("FORWARDED_ALLOW_IPS must never use '*'")
        for item in items:
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError as exc:
                raise ValueError(f"Invalid FORWARDED_ALLOW_IPS entry: {item!r}") from exc
        return ",".join(items)

    @field_validator("usdt_tron_account_xpub")
    @classmethod
    def _normalize_tron_account_xpub(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("environment")
    @classmethod
    def _validate_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _VALID_ENVIRONMENTS:
            raise ValueError(
                f"ENVIRONMENT must be one of {sorted(_VALID_ENVIRONMENTS)}, got {value!r}. "
                "A typo here would otherwise silently skip production hardening checks."
            )
        return normalized

    @model_validator(mode="after")
    def _production_security_requirements(self):
        if self.environment in {"staging", "production"}:
            if self.usdt_tron_enabled and not self.usdt_tron_account_xpub:
                raise ValueError("USDT_TRON_ACCOUNT_XPUB is required when TRON deposits are enabled")
            if self.process_role == "api":
                if not self.supabase_url or not self.supabase_anon_key:
                    raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY are required for the API in staging/production")
                if not self.funding_webhook_secret:
                    raise ValueError("FUNDING_WEBHOOK_SECRET is required for the API in staging/production")
            if self.model_integrity_required_for_live and self.adaptive_ai_enabled:
                if not self.model_signing_public_key:
                    raise ValueError("MODEL_SIGNING_PUBLIC_KEY is required for model integrity in staging/production")
                if self.process_role == "worker" and not self.model_signing_private_key:
                    raise ValueError("MODEL_SIGNING_PRIVATE_KEY is required for adaptive worker model promotion")
            if self.process_role == "api" and not self.forwarded_allow_ips:
                raise ValueError("FORWARDED_ALLOW_IPS must be explicitly configured for the API in staging/production")
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

