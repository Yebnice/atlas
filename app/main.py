from __future__ import annotations
from pathlib import Path
import hmac
import os
import base64
import asyncio
import re
import hashlib
import time
import json
import base64
import uuid
from decimal import Decimal
from contextvars import ContextVar
from dataclasses import asdict
import pandas as pd
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, desc, or_, func
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import init_db, engine, SessionLocal, AppState, TradingAccount, Trade, Position, AuditLog, Withdrawal, CustomerProfile, Wallet, FundingTransaction, WithdrawalStepUpToken, WithdrawalOtpIntent, ServiceHeartbeat, OandaReconciliationState, Plan, Subscription, ReferralCode, Referral, ReferralCommission, RevenueLedger, CostLedger, SmartTrade, DcaBot, CustomerAlert, StrategyDraft, ArbitrageOpportunity, CustomerLedgerAccount, LedgerEntry, TronDepositCursor, TronSweep, CustomerBinanceAccount, LiveExecutionLease, CustomerOandaAccount, CustomerDerivAccount, StripeWebhookEvent, GridBot, AdaptiveTradingBot, StrategyCandidate, StrategyCandidateRun, TradeExecutor, WebhookEndpoint, WebhookEvent, ExchangeConnector, ModelExperiment, ResearchRun, StrategyOutcome, TradeLearningEpisode, TradeReplayResult, AdminRole, WithdrawalDestination, Incident, quantize_money
from .data import fetch_crypto, fetch_forex, fetch_forex_oanda
from .trading_core import train_model, predict_latest, ai_walk_forward_backtest, PROFILES
from .adaptive_bot import AdaptiveModelPolicy, ensure_adaptive_model, adaptive_model_status
from .strategy_engine import StrategyConfig, strategy_signal, strategy_backtest
from .strategy_router import select_strategy, policy_walk_forward_backtest, strategy_trade_plan, online_strategy_scores, classify_regime
from .trade_learning import process_trade_learning_episodes
from .entry_exit_engine import EntryExitConfig, gated_entry_exit_analysis, start_bot_decision, gated_entry_exit_backtest
from .ai_providers import dual_ai_trade_safety_review, AIProviderError
from .strategy_ai import generate_strategy_draft
from .research_engine import backtest_all_strategies, ai_market_review, paper_candidates, live_strategy_signals
from .research_validation import oos_promotion_gate, monte_carlo_bootstrap, parameter_plateau_score
from .daily_research import run_daily_research
from .execution import execute_signal, reconcile, emergency_stop, RiskBlocked, mark_paper_equity, reconcile_customer_live_orders
from .live_execution import assert_live_system_enabled, LiveExecutionBlocked
from .payout import get_payout_provider, PayoutError, PayoutUnknown
from .withdrawal_security import destination_allowed, destination_fingerprint, proposal_digest, verify_release_operator
from .usdt_tron import derive_usdt_tron_address_from_xpub, validate_tron_account_xpub
from .tron_sweep import build_sweep_intent, serialize_sweep_intent, SweepError, classify_solidified_sweep
from .customer_funds import get_or_create_ledger, post_deposit, sync_wallet_from_ledger, customer_balance, ledger_statement, reserve_withdrawal, release_withdrawal as ledger_release_withdrawal, settle_withdrawal
from .distributed import allow_rate_limit, check_redis, acquire_lock, release_lock, refresh_lock
from .withdrawal_risk import score_withdrawal
from .security_audit import emit_security_audit
from .incidents import open_incident
from .model_registry import verify_model_file, backup_champion, rollback_champion
from .correlation_risk import adjusted_group_exposure
from .custody_signer import custody_signing_required, validate_signer_config
from .meta_labeling import meta_label_gate
from .derivatives_context import fetch_public_derivatives_context
from .multi_timeframe import multi_timeframe_signal
from .grid_trading import build_grid, grid_profit_pct
from .arbitrage import TriangleQuote, evaluate_triangle
from .execution_optimizer import BookLevel, build_execution_plan
from .fx_engine import FXModelConfig, fx_model_signal, fx_walk_forward_score
from .deriv import DerivBroker, DerivConfig, DerivError, DerivUnknown
from .binance_arbitrage_live import BinanceArbitrageBroker, BinanceArbConfig, BinanceArbitrageError
from .binance_subaccounts import build_provision_plan, BinanceSubAccountError
from .customer_oanda import build_customer_oanda_broker
from .executor_engine import ExecutorConfig, ExecutorValidationError, build_executor_plan, next_slice
from .admin_rbac import require_role, get_roles, upsert_role, ROLES
from .transaction_policy import register_or_check_destination, verify_destination
from .audit_chain import append_audit

def _stepup_token(uid: str, purpose: str = "withdrawal", destination_fingerprint: str = "", proposal_digest_value: str = "") -> tuple[str, str, int]:
    if not settings.secret_key:
        raise HTTPException(503, "Step-up authentication is not configured")
    now = int(time.time())
    exp = now + settings.withdrawal_step_up_minutes * 60
    jti = uuid.uuid4().hex
    payload = {"uid": uid, "purpose": purpose, "destination_fingerprint": destination_fingerprint, "proposal_digest": proposal_digest_value, "exp": exp, "jti": jti}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    sig = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return body + "." + sig, jti, exp


def _parse_stepup_token(token: str | None, uid: str, purpose: str = "withdrawal", destination_fingerprint: str = "", proposal_digest_value: str = "") -> tuple[str, int, str] | None:
    if not token or not settings.secret_key or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        jti = str(payload.get("jti") or "")
        exp = int(payload.get("exp", 0))
        token_fp = str(payload.get("destination_fingerprint") or "")
        token_digest = str(payload.get("proposal_digest") or "")
        if not jti or payload.get("uid") != uid or payload.get("purpose") != purpose or token_fp != str(destination_fingerprint or "") or token_digest != str(proposal_digest_value or "") or exp < int(time.time()):
            return None
        return jti, exp, token_fp
    except Exception:
        return None


def verify_local_signature(signature: str, digest: str) -> bool:
    if not settings.local_signing_enabled or not settings.local_signing_public_key or not signature:
        return False
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = serialization.load_pem_public_key(settings.local_signing_public_key.encode())
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(base64.b64decode(signature), digest.encode())
        return True
    except Exception:
        return False
from .monitoring import TelemetryMiddleware, metrics_response, logger


docs_url = "/docs" if settings.docs_enabled else None
redoc_url = "/redoc" if settings.docs_enabled else None
app = FastAPI(title=settings.app_name, version=settings.app_version, docs_url=docs_url, redoc_url=redoc_url)
_APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(_APP_DIR / "static")), name="static")
app.add_middleware(TelemetryMiddleware)

_instance_id = os.getenv("K_REVISION", "local") + ":" + uuid.uuid4().hex[:12]
_background_task: asyncio.Task | None = None
_usdt_task: asyncio.Task | None = None
_worker_tasks: set[asyncio.Task] = set()
_audit_actor: ContextVar[str] = ContextVar("atlas_audit_actor", default="system")
_expensive_paths = {"/api/train", "/api/backtest", "/api/strategy/backtest", "/api/customer/bot/start"}

@app.middleware("http")
async def api_rate_limit(request: Request, call_next):
    if request.url.path in {"/health", "/healthz", "/readyz"}:
        return await call_next(request)
    if request.url.path.startswith("/api/auth/otp/"):
        bucket, limit = "otp", settings.otp_rate_limit_per_minute
    elif request.url.path.startswith("/api/auth/"):
        bucket, limit = "auth", settings.auth_rate_limit_per_minute
    else:
        bucket = "expensive" if request.url.path in _expensive_paths else "normal"
        limit = settings.expensive_api_rate_limit_per_minute if bucket == "expensive" else settings.api_rate_limit_per_minute
    client = _trusted_client_ip(request)
    # IMPORTANT: client IP and authenticated identity are independent mandatory dimensions.
    # Client-controlled device identifiers are never allowed to create a fresh quota bucket.
    auth_raw = str(request.headers.get("authorization") or "")
    auth_id = hashlib.sha256(auth_raw.encode()).hexdigest()[:24] if auth_raw else "anon"
    allowed_ip, _ = await allow_rate_limit(f"{bucket}:ip:{client}", max(1, limit))
    if not allowed_ip:
        return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"})
    if auth_raw:
        allowed_identity, _ = await allow_rate_limit(f"{bucket}:auth:{auth_id}", max(1, limit))
        if not allowed_identity:
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"})
    return await call_next(request)


def _track_worker_task(coro):
    task = asyncio.create_task(coro)
    _worker_tasks.add(task)
    task.add_done_callback(_worker_tasks.discard)
    return task


def _trusted_client_ip(request: Request) -> str:
    """Resolve client IP only from a trusted reverse-proxy chain.

    Uvicorn itself also honors FORWARDED_ALLOW_IPS. The application only parses
    X-Forwarded-For when that environment is explicitly configured; otherwise it
    uses the direct peer IP and fails closed against client-spoofed forwarding headers.
    """
    peer = str(request.client.host if request.client else "unknown")
    trusted = {x.strip() for x in str(settings.forwarded_allow_ips or "").split(",") if x.strip()}
    if not trusted:
        return peer
    try:
        import ipaddress
        peer_ip = ipaddress.ip_address(peer)
        trusted_peers = [ipaddress.ip_network(x, strict=False) for x in trusted]
        if not any(peer_ip in net for net in trusted_peers):
            return peer
    except Exception:
        return peer
    forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
    if not forwarded:
        return peer
    import ipaddress
    # XFF is ordered client -> proxy -> proxy. Only trust the chain from the
    # known peer inward: the first untrusted hop encountered from the right is
    # the client. Any malformed/empty token fails closed because skipping it can
    # change which hop is treated as authoritative.
    raw_chain = [raw.strip() for raw in forwarded.split(",")]
    if not raw_chain or any(not raw for raw in raw_chain):
        return peer
    try:
        chain = [ipaddress.ip_address(raw) for raw in raw_chain]
    except ValueError:
        return peer
    for candidate_ip in reversed(chain):
        if not any(candidate_ip in net for net in trusted_peers):
            return str(candidate_ip)
    return str(chain[0]) if chain else peer


async def _assert_database_migrations_current() -> None:
    """Fail closed in staging/production when the database is not at Alembic head."""
    if str(settings.environment).lower() == "development":
        return
    try:
        from alembic.config import Config as AlembicConfig
        from alembic.migration import MigrationContext
        from alembic.script import ScriptDirectory
        cfg = AlembicConfig(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        expected = set(ScriptDirectory.from_config(cfg).get_heads())
        async with engine.connect() as conn:
            current = await conn.run_sync(lambda sync_conn: set(MigrationContext.configure(sync_conn).get_current_heads()))
        if current != expected:
            raise RuntimeError(f"Database migrations are not at Alembic head: current={sorted(current)} expected={sorted(expected)}; run 'alembic upgrade head' before starting Atlas")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Unable to verify Alembic migration state: {exc}") from exc


@app.on_event("startup")
async def startup():
    global _background_task, _usdt_task
    if settings.forex_live_enabled:
        raise RuntimeError("OANDA live trading is permanently disabled in AtlasRisk; use OANDA practice/demo for learning and backtesting")
    if settings.deriv_live_enabled:
        raise RuntimeError("Deriv real-account live execution is disabled until it is integrated into the unified live execution outbox/ledger path")
    if settings.binance_arbitrage_live_enabled:
        raise RuntimeError("Binance arbitrage live execution is disabled until it is integrated into the unified live execution outbox/ledger path")
    live_requested = any((
        settings.live_trading_enabled,
        settings.customer_live_trading_enabled,
        settings.forex_live_enabled,
        settings.deriv_live_enabled,
        settings.payout_live_enabled,
        settings.usdt_tron_sweep_enabled,
    ))
    if settings.database_url.lower().startswith("sqlite") and settings.environment.lower() in {"production", "staging"}:
        raise RuntimeError("PostgreSQL is required outside development; SQLite row-level locks are unavailable")
    if settings.environment.lower() == "production":
        try:
            from .crypto import validate_encryption_config
            validate_encryption_config()
        except Exception as exc:
            raise RuntimeError(f"Encryption configuration is invalid: {exc}") from exc
        if not settings.secret_key:
            raise RuntimeError("SECRET_KEY is required in production")
        if settings.distributed_rate_limit_required and not settings.redis_url:
            raise RuntimeError("REDIS_URL is required in production for distributed rate limiting")
        if settings.payout_live_enabled and not settings.external_custody_signer_required:
            raise RuntimeError("EXTERNAL_CUSTODY_SIGNER_REQUIRED=true is mandatory for production live payouts")
        if settings.adaptive_bot_controller_enabled and not settings.redis_url:
            # The per-model training lock uses the same distributed lock, which refuses
            # unconditionally in production without Redis: every adaptive bot cycle would
            # silently return MODEL_LOCK_BUSY forever and no model would ever train.
            raise RuntimeError("REDIS_URL is required in production when adaptive bot training/promotion is enabled")
        if settings.require_backup_recovery_config and not settings.backup_recovery_url:
            raise RuntimeError("BACKUP_RECOVERY_URL is required in production")
        if settings.external_security_audit_required and not settings.external_security_audit_enabled:
            raise RuntimeError("EXTERNAL_SECURITY_AUDIT_ENABLED must remain true in production")
        if settings.payout_live_enabled:
            if not settings.withdrawals_enabled:
                raise RuntimeError("PAYOUT_LIVE_ENABLED requires WITHDRAWALS_ENABLED=true")
            if str(settings.payout_provider).lower() == "disabled":
                raise RuntimeError("PAYOUT_LIVE_ENABLED requires an explicit PAYOUT_PROVIDER")
            if str(settings.payout_provider).lower() == "ccxt":
                raise RuntimeError("Direct CCXT withdrawals are prohibited in production; use the external signer custody boundary")
            if settings.external_custody_signer_required:
                validate_signer_config()
        if int(os.getenv("WEB_CONCURRENCY", "1")) > 1 and settings.require_single_worker_for_live and settings.live_trading_enabled:
            raise RuntimeError("Live trading requires a distributed execution lock before multi-worker deployment")
    if settings.usdt_tron_enabled:
        from .usdt_tron import require_tron_wallet_backend
        require_tron_wallet_backend()
    await _assert_database_migrations_current()
    await init_db()
    async with SessionLocal() as billing_db:
        await _ensure_billing_plans(billing_db)
        await billing_db.commit()
    process_role = str(settings.process_role or os.getenv("ATLAS_PROCESS_ROLE", "api")).lower().strip()
    if process_role not in {"api", "worker", "job"}:
        raise RuntimeError("PROCESS_ROLE/ATLAS_PROCESS_ROLE must be api, worker, or job")
    # HTTP services expose the API only. Continuous reconciliation, custody scanning,
    # adaptive controllers and recovery loops belong to the worker pool.
    if process_role == "worker":
        if settings.background_reconciliation_enabled:
            _background_task = _track_worker_task(_reconciliation_loop())
        if settings.usdt_tron_enabled and settings.usdt_trongrid_api_key:
            _usdt_task = _track_worker_task(_usdt_tron_monitor_loop())
        _track_worker_task(_heartbeat_loop())
        _track_worker_task(_withdrawal_recovery_loop())
        if settings.daily_research_enabled:
            _track_worker_task(_daily_research_loop())
        if settings.adaptive_bot_controller_enabled:
            _track_worker_task(_adaptive_bot_controller_loop())
            _track_worker_task(_executor_controller_loop())
    elif process_role == "job":
        _track_worker_task(_heartbeat_loop())


@app.on_event("shutdown")
async def shutdown():
    global _background_task, _usdt_task
    tasks = set(_worker_tasks)
    for task in (_background_task, _usdt_task):
        if task:
            tasks.add(task)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _worker_tasks.clear()
    _background_task = None
    _usdt_task = None


async def _record_model_experiment(model_path: str, asset: str, result: dict) -> None:
    """Persist a retrain attempt / drift reading. Best-effort: tracking must never break trading."""
    try:
        status = str(result.get("status", ""))
        drift = result.get("feature_drift") or {}
        # CHAMPION_FRESH fires every bot cycle; only record it when drift is noteworthy,
        # otherwise the table would grow by a row per cycle per bot forever.
        if status == "CHAMPION_FRESH" and drift.get("status") not in ("WARN", "ALERT"):
            return
        if status not in ("CHAMPION_PROMOTED", "CHALLENGER_REJECTED", "CHAMPION_FRESH"):
            return
        async with SessionLocal() as db:
            db.add(ModelExperiment(
                model_path=model_path[:400], asset=asset, status=status,
                model_sha256=str(result.get("model_version", "")),
                gate_json=json.dumps(result.get("gate") or {}, default=str),
                wfo_json=json.dumps(result.get("wfo") or {}, default=str),
                feature_drift_json=json.dumps(drift, default=str),
            ))
            await db.commit()
        if drift.get("status") == "ALERT":
            await _audit("MODEL_FEATURE_DRIFT_ALERT", {"model_path": model_path, "asset": asset, "mean_psi": drift.get("mean_psi"), "max_psi_feature": drift.get("max_psi_feature")})
    except Exception:
        pass


async def _ensure_adaptive_model_locked(req: MarketRequest, df, policy: AdaptiveModelPolicy) -> dict:
    """Serialize shared model training/promotion per market artifact."""
    model_path = model_file(req)
    lock_key = "adaptive-model:" + hashlib.sha256(model_path.encode("utf-8")).hexdigest()
    if not await acquire_lock(lock_key, ttl_seconds=1800):
        return {"status": "MODEL_LOCK_BUSY", "promotion": "RETRY_LATER"}
    try:
        result = await asyncio.to_thread(
            ensure_adaptive_model, df, model_path, asset=req.asset,
            min_train=settings.research_min_train, folds=settings.research_folds,
            threshold=settings.research_ai_threshold, policy=policy,
        )
        await _record_model_experiment(model_path, req.asset, result)
        return result
    finally:
        await release_lock(lock_key)


async def _adaptive_bot_runtime_gate(bot_id: int, customer_id: int, trading_account_id: int) -> tuple[bool, bool, str]:
    """Re-check mutable customer, billing and risk state immediately before execution."""
    async with SessionLocal() as db:
        bot = await db.get(AdaptiveTradingBot, bot_id)
        profile = await db.get(CustomerProfile, customer_id)
        account = await db.get(TradingAccount, trading_account_id)
        state = await db.get(AppState, 1)
        if not bot or bot.status != "RUNNING":
            return False, True, "bot_stopped"
        if not profile or profile.status != "ACTIVE":
            return False, True, "customer_inactive"
        if not account or account.status != "ACTIVE":
            return False, True, "trading_account_inactive"
        if not state or state.kill_switch:
            return False, True, "platform_kill_switch"
        plan, _ = await _subscription_entitlements(db, customer_id)
        if "automated_entry_exit" not in plan.get("features", []):
            bot.status = "STOPPED"
            bot.next_run_at = None
            bot.last_error = "Automation entitlement is no longer active"
            await db.commit()
            return False, True, "automation_entitlement"
        live_requested = bot.mode == "LIVE"
        paper_mode = bool(settings.paper_trading or not settings.live_trading_enabled or not state.live_enabled or not live_requested)
        if live_requested and (not plan.get("live") or not settings.customer_live_trading_enabled):
            bot.status = "STOPPED"
            bot.next_run_at = None
            bot.last_error = "Live automation entitlement or customer-live gate is no longer active"
            await db.commit()
            return False, True, "live_entitlement"
        return True, paper_mode, "ok"


async def _adaptive_bot_controller_loop():
    """Continuously run persisted customer adaptive bots on completed-bar schedules.

    START requires customer AAL2 and creates an approved persistent controller. The loop
    never bypasses the normal market-quality, ML, AI-safety, risk, ledger and execution gates.
    """
    poll = max(10, int(settings.adaptive_bot_poll_seconds))
    while True:
        try:
            now = datetime.now(timezone.utc)
            async with SessionLocal() as db:
                bots = (await db.execute(select(AdaptiveTradingBot).where(AdaptiveTradingBot.status == "RUNNING", or_(AdaptiveTradingBot.next_run_at.is_(None), AdaptiveTradingBot.next_run_at <= now)).order_by(AdaptiveTradingBot.id).limit(25))).scalars().all()
                work = [(b.id, b.customer_id, b.trading_account_id, b.asset, b.symbol, b.exchange, b.timeframe, b.days, b.risk_fraction, b.interval_seconds, b.mode) for b in bots]
            for bot_id, customer_id, account_id, asset, symbol, exchange, timeframe, days, risk_fraction, interval_seconds, mode in work:
                lock_key = f"adaptive-bot:{bot_id}"
                if not await acquire_lock(lock_key, ttl_seconds=max(120, int(interval_seconds) + 120)):
                    continue
                try:
                    req = CustomerBotStartRequest(asset=asset, symbol=symbol, exchange=exchange, timeframe=timeframe, days=days, risk_fraction=risk_fraction, autonomous=False, interval_seconds=interval_seconds)
                    # The Redis scheduler lease can expire while a slow market/model cycle runs.
                    # Refreshing immediately before the execution path prevents an expired worker
                    # from submitting a trade after another worker acquired the bot lock.
                    if not await refresh_lock(lock_key, ttl_seconds=max(120, int(interval_seconds) + 120)):
                        continue
                    # Reuse the authenticated execution path through a dedicated internal runner.
                    result = await _run_persisted_adaptive_bot_cycle(bot_id, req)
                    async with SessionLocal() as db:
                        row = await db.get(AdaptiveTradingBot, bot_id)
                        if row:
                            row.last_run_at = now
                            row.next_run_at = now + __import__("datetime").timedelta(seconds=max(60, interval_seconds))
                            row.last_decision = str(result.get("decision", "ERROR"))
                            row.last_stage = str(result.get("stage", "execution"))
                            row.last_model_version = str((result.get("ml_signal") or {}).get("model_version", ""))
                            row.last_error = ""
                            row.consecutive_errors = 0
                            await db.commit()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    async with SessionLocal() as db:
                        row = await db.get(AdaptiveTradingBot, bot_id)
                        if row:
                            row.last_run_at = now
                            row.consecutive_errors = int(row.consecutive_errors or 0) + 1
                            if row.consecutive_errors >= 3:
                                row.status = "STOPPED"
                                row.next_run_at = None
                            else:
                                row.next_run_at = now + __import__("datetime").timedelta(seconds=max(60, interval_seconds))
                            row.last_decision = "ERROR"
                            row.last_stage = "controller"
                            row.last_error = str(exc)[:2000]
                            await db.commit()
                finally:
                    await release_lock(lock_key)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _audit("ADAPTIVE_BOT_CONTROLLER_FAILED", {"error": str(exc)})
        await asyncio.sleep(poll)


async def _fetch_customer_oanda_data(customer_id: int, req: CustomerBotStartRequest):
    async with SessionLocal() as cdb:
        customer_oanda = (await cdb.execute(select(CustomerOandaAccount).where(CustomerOandaAccount.customer_id == customer_id))).scalar_one_or_none()
    if customer_oanda is None or str(customer_oanda.status).upper() != "VERIFIED" or not customer_oanda.can_trade:
        raise RuntimeError("Customer OANDA account is not configured and verified")
    broker = build_customer_oanda_broker(customer_oanda, timeout_seconds=settings.oanda_timeout_seconds)
    try:
        gran = {"1m":"M1","5m":"M5","15m":"M15","30m":"M30","1h":"H1","4h":"H4","1d":"D"}.get(req.timeframe)
        if not gran:
            raise RuntimeError("Unsupported OANDA timeframe")
        # Bar count must scale with the bot's real timeframe. A fixed "days * 24" (hourly)
        # assumption starves sub-hourly bots of history, so their model can never reach
        # min_train samples and never trains.
        bars_per_day = {"1m": 1440, "5m": 288, "15m": 96, "30m": 48, "1h": 24, "4h": 6, "1d": 1}[req.timeframe]
        candles = await asyncio.to_thread(broker.candles, req.symbol, gran, min(5000, max(250, req.days * bars_per_day)))
        rows=[]
        for c in candles:
            if c.get("complete"):
                m=c.get("mid") or {}
                rows.append([c.get("time"),float(m.get("o")),float(m.get("h")),float(m.get("l")),float(m.get("c")),float(c.get("volume") or 0)])
        if not rows:
            raise RuntimeError("No completed OANDA candles returned")
        df=pd.DataFrame(rows,columns=["ts","open","high","low","close","volume"])
        df["ts"]=pd.to_datetime(df["ts"],utc=True)
        return df.set_index("ts").sort_index()
    finally:
        broker.close()


async def _run_persisted_adaptive_bot_cycle(bot_id: int, req: CustomerBotStartRequest) -> dict:
    """Run one persisted bot cycle under the same gates as customer Start Bot."""
    async with SessionLocal() as db:
        bot = (await db.execute(select(AdaptiveTradingBot).where(AdaptiveTradingBot.id == bot_id).with_for_update())).scalar_one_or_none()
        if not bot or bot.status != "RUNNING":
            return {"decision": "NO_TRADE", "stage": "controller_stopped"}
        profile = await db.get(CustomerProfile, bot.customer_id)
        account = await db.get(TradingAccount, bot.trading_account_id)
        state = await db.get(AppState, 1)
        if not profile or not account or account.status != "ACTIVE" or not state or state.kill_switch:
            return {"decision": "NO_TRADE", "stage": "risk_state"}
        equity = max(0.0, float(account.equity))
        risk_fraction = float(bot.risk_fraction or settings.risk_per_trade)
        paper_mode = bool(settings.paper_trading or not settings.live_trading_enabled or not state.live_enabled or bot.mode != "LIVE")
    if req.asset in {"forex", "commodity"}:
        try:
            df = await _fetch_customer_oanda_data(profile.id, req)
        except Exception as exc:
            return {"decision": "NO_TRADE", "stage": "customer_oanda_data_gate", "reason": str(exc)}
    else:
        df = await asyncio.to_thread(market_data, req)
    data_safe, data_reasons = _market_data_quality(df, req.timeframe, req.asset)
    spread_bps = await _customer_oanda_spread_bps(profile.id, req.symbol) if req.asset in {"forex", "commodity"} else await asyncio.to_thread(_current_spread_bps, req)
    if spread_bps is None and not paper_mode:
        data_safe = False
        data_reasons.append("live_spread_unavailable")
    derivatives_context = {"status":"DISABLED"}
    if req.asset == "crypto" and settings.derivatives_risk_enabled:
        try:
            derivatives_context = await fetch_public_derivatives_context(req.exchange, req.symbol)
        except Exception as exc:
            derivatives_context = {"status":"ERROR","reason":str(exc)}
        if not paper_mode and settings.derivatives_risk_fail_closed_live and derivatives_context.get("status") in {"ERROR","UNAVAILABLE","UNSUPPORTED_EXCHANGE","SYMBOL_UNAVAILABLE"}:
            return {"decision":"NO_TRADE","stage":"derivatives_context_gate","reason":"Live derivatives risk context unavailable","derivatives_context":derivatives_context}
        if not paper_mode and derivatives_context.get("state") == "SEVERE":
            await open_incident(key=f"DERIVATIVES_STRESS:{profile.id}:{req.symbol}",severity="HIGH",category="MARKET_STRESS",summary="Live entry blocked by severe derivatives stress",detail=derivatives_context,customer_id=profile.id)
            return {"decision":"NO_TRADE","stage":"derivatives_stress_gate","derivatives_context":derivatives_context}

    policy = AdaptiveModelPolicy(max_age_hours=settings.adaptive_retrain_hours, min_sharpe=settings.adaptive_min_sharpe, max_drawdown=settings.adaptive_max_drawdown, min_trades=settings.adaptive_min_trades, min_total_return=settings.adaptive_min_total_return)
    # Learning is independent of trade opportunity: the controller retrains/backtests
    # on schedule even when the current candle produces no deterministic setup.
    adaptive = await _ensure_adaptive_model_locked(req, df, policy)
    drift = adaptive.get("feature_drift") or {}
    if not paper_mode and settings.model_drift_alert_blocks_live and drift.get("status") == "ALERT":
        async with SessionLocal() as idb:
            ibot = await idb.get(AdaptiveTradingBot, bot_id)
            if ibot:
                ibot.status = "HALTED_DRIFT"; ibot.next_run_at = None; ibot.last_error = "Model feature drift ALERT; live entries halted pending review"
                await idb.commit()
        await open_incident(key=f"MODEL_DRIFT:{bot_id}", severity="HIGH", category="MODEL_DRIFT", summary="Live adaptive bot halted by feature drift ALERT", detail={"bot_id":bot_id,"customer_id":profile.id,"symbol":req.symbol,"drift":drift}, customer_id=profile.id)
        await _audit("MODEL_DRIFT_LIVE_HALT", {"bot_id":bot_id,"customer_id":profile.id,"drift":drift})
        return {"decision":"NO_TRADE","stage":"model_drift_alert","analysis":{},"adaptive_model":adaptive,"drift":drift}
    if not paper_mode and settings.model_require_feature_baseline_for_live and drift.get("status") in {"NO_BASELINE","INSUFFICIENT_DATA","ERROR"}:
        return {"decision":"NO_TRADE","stage":"model_drift_baseline_gate","adaptive_model":adaptive,"drift":drift}
    model_meta = adaptive_model_status(model_file(req), policy)
    if not paper_mode and settings.model_integrity_required_for_live:
        meta_sha = str(model_meta.get("model_version") or "")
        if not verify_model_file(model_file(req), meta_sha):
            await open_incident(key=f"MODEL_INTEGRITY:{req.asset}:{req.symbol}", severity="CRITICAL", category="MODEL_INTEGRITY", summary="Live model artifact integrity verification failed", detail={"model_path":str(model_file(req)),"model_version":meta_sha})
            return {"decision":"NO_TRADE","stage":"model_integrity_gate","adaptive_model":adaptive}
    deterministic = await asyncio.to_thread(start_bot_decision, df, EntryExitConfig(), ai_safe=True, data_safe=data_safe, spread_bps=spread_bps)
    deterministic["data_quality"] = {"safe": data_safe, "reasons": data_reasons, "spread_bps": spread_bps, "derivatives_context": derivatives_context}
    if deterministic["decision"] != "TRADE":
        return {"decision": "NO_TRADE", "stage": "deterministic_gate", "analysis": deterministic, "adaptive_model": adaptive}
    mtf_context={"status":"SKIPPED"}
    if req.asset == "crypto" and req.timeframe in {"5m","15m"}:
        try:
            mtf_context = await asyncio.to_thread(multi_timeframe_signal, df)
        except Exception as exc:
            mtf_context={"status":"ERROR","reason":str(exc)}
        if not mtf_context.get("confirmed",False):
            return {"decision":"NO_TRADE","stage":"multi_timeframe_gate","analysis":deterministic,"adaptive_model":adaptive,"mtf_context":mtf_context}
        if mtf_context.get("side") != deterministic.get("trade_plan",{}).get("side"):
            return {"decision":"NO_TRADE","stage":"multi_timeframe_alignment","analysis":deterministic,"adaptive_model":adaptive,"mtf_context":mtf_context}
    meta_label = await asyncio.to_thread(meta_label_gate, df, horizon=settings.meta_label_horizon_bars, min_edge_bps=settings.meta_label_min_edge_bps, threshold=settings.meta_label_probability_threshold) if settings.meta_labeling_enabled else {"status":"DISABLED","take_trade":True}
    if not meta_label.get("take_trade", False):
        return {"decision":"NO_TRADE","stage":"meta_label_gate","analysis":deterministic,"adaptive_model":adaptive,"meta_label":meta_label}
    if adaptive.get("status") == "CHALLENGER_REJECTED" and adaptive.get("promotion") == "NO_MODEL":
        return {"decision": "NO_TRADE", "stage": "adaptive_model_gate", "analysis": deterministic, "adaptive_model": adaptive}
    if not model_meta.get("fresh", False):
        return {"decision": "NO_TRADE", "stage": "adaptive_model_stale", "analysis": deterministic, "adaptive_model": adaptive}
    ml_signal = await asyncio.to_thread(predict_latest, df, model_file(req), settings.research_ai_threshold)
    plan = deterministic["trade_plan"]
    deterministic_side = str(plan["side"])
    ml_side = "buy" if ml_signal["signal"] > 0 else ("sell" if ml_signal["signal"] < 0 else "flat")
    if deterministic_side != ml_side:
        return {"decision": "NO_TRADE", "stage": "adaptive_model_confirmation", "analysis": deterministic, "adaptive_model": adaptive, "meta_label": meta_label, "ml_signal": ml_signal}
    packet = {"symbol": req.symbol, "asset": req.asset, "exchange": req.exchange, "timeframe": req.timeframe, "market_timestamp": deterministic["timestamp"], "trade_plan": plan, "deterministic_rules": deterministic["rules"], "price_context": {"latest_close": float(df.close.iloc[-1]), "bars": int(len(df)), "spread_bps": spread_bps}, "data_quality": deterministic["data_quality"], "adaptive_model": adaptive, "ml_signal": ml_signal}
    ai_review = await dual_ai_trade_safety_review(packet)
    if not ai_review["safe"]:
        stage = "ai_safety_not_configured" if not ai_review.get("configured", True) else "ai_safety_gate"
        await _audit("ADAPTIVE_BOT_AI_VETO" if stage == "ai_safety_gate" else "ADAPTIVE_BOT_AI_NOT_CONFIGURED",
                     {"bot_id": bot_id, "customer_id": profile.id, "symbol": req.symbol, "ai_review": ai_review})
        return {"decision": "NO_TRADE", "stage": stage, "analysis": deterministic, "adaptive_model": adaptive, "ml_signal": ml_signal, "ai_review": ai_review}
    distance = abs(float(plan["entry_price"]) - float(plan["stop_loss_price"]))
    if distance <= 0:
        return {"decision": "NO_TRADE", "stage": "risk_distance"}
    risk_cash = equity * float(risk_fraction or settings.risk_per_trade)
    quantity = min(risk_cash / distance, settings.max_notional_usd / max(float(plan["entry_price"]), 1e-12))
    if derivatives_context.get("state") == "ELEVATED":
        quantity *= max(0.0, min(1.0, settings.derivatives_elevated_size_multiplier))
    if quantity <= 0:
        return {"decision": "NO_TRADE", "stage": "risk_quantity"}
    allowed, paper_mode, gate_reason = await _adaptive_bot_runtime_gate(bot_id, profile.id, account.id)
    if not allowed:
        return {"decision": "NO_TRADE", "stage": "runtime_gate", "reason": gate_reason, "analysis": deterministic, "adaptive_model": adaptive, "ml_signal": ml_signal, "ai_review": ai_review}
    signal = {"score": float(deterministic.get("reward_risk", 0.0)), "side": plan["side"], "deterministic_gate": deterministic, "ai_safety_review": ai_review, "customer_id": profile.id, "trading_account_id": account.id}
    execution = await execute_signal(req.symbol, plan["side"], quantity, float(plan["entry_price"]), signal, req.exchange, req.timeframe, deterministic["timestamp"], force_paper=paper_mode, stop_loss_price=float(plan["stop_loss_price"]), take_profit_price=float(plan["take_profit_price"]), strategy="atlas-adaptive-autonomous-v1", asset=req.asset, customer_id=profile.id)
    return {"decision": "TRADE", "mode": execution.get("mode"), "analysis": deterministic, "adaptive_model": adaptive, "ml_signal": ml_signal, "ai_review": ai_review, "trade_plan": {**plan, "quantity": quantity, "risk_cash": risk_cash}, "execution": execution}


async def _executor_controller_loop():
    """Run persisted DCA/TWAP executors with a fresh live-authority check per slice."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            async with SessionLocal() as db:
                rows = (await db.execute(
                    select(TradeExecutor).where(
                        TradeExecutor.status == "ARMED",
                        or_(TradeExecutor.next_run_at.is_(None), TradeExecutor.next_run_at <= now),
                    ).order_by(TradeExecutor.id).limit(25)
                )).scalars().all()
                work = [r.id for r in rows]
            for eid in work:
                lock_key = f"executor:{eid}"
                if not await acquire_lock(lock_key, ttl_seconds=180):
                    continue
                try:
                    async with SessionLocal() as db:
                        row = (await db.execute(select(TradeExecutor).where(TradeExecutor.id == eid).with_for_update())).scalar_one_or_none()
                        if not row or row.status != "ARMED":
                            continue
                        cid, asset, exchange, symbol, timeframe = row.customer_id, row.asset, row.exchange, row.symbol, row.timeframe
                        cfg = json.loads(row.config_json or "{}")
                        executed = float(row.executed_quantity or 0)
                        target = float(row.target_quantity or 0)
                        mode = str(row.mode or "PAPER").upper()
                        live_approved = bool(row.live_approved)
                        if mode == "LIVE":
                            profile = await db.get(CustomerProfile, cid)
                            account = await db.get(TradingAccount, row.trading_account_id)
                            state = await db.get(AppState, 1)
                            plan, _ = await _subscription_entitlements(db, cid)
                            live_ok = bool(
                                live_approved and profile and profile.status == "ACTIVE" and account and account.status == "ACTIVE"
                                and state and not state.kill_switch and state.live_enabled
                                and settings.customer_live_trading_enabled and settings.live_trading_enabled and not settings.paper_trading
                                and not settings.broker_sandbox and bool(plan.get("live"))
                            )
                            if not live_ok:
                                row.status = "STOPPED"
                                row.next_run_at = None
                                row.last_error = "Live authority or customer entitlement is no longer valid"
                                await db.commit()
                                continue
                        req = CustomerBotStartRequest(asset=asset, symbol=symbol, exchange=exchange, timeframe=timeframe, days=365, autonomous=False)
                    if target <= 0:
                        async with SessionLocal() as db:
                            row = await db.get(TradeExecutor, eid, with_for_update=True)
                            if row:
                                row.status = "COMPLETED"; row.next_run_at = None; await db.commit()
                        continue
                    df = await _fetch_customer_oanda_data(cid, req) if asset in {"forex", "commodity"} else await asyncio.to_thread(market_data, req)
                    price = float(df.close.iloc[-1])
                    sl = next_slice(cfg, executed)
                    if sl is None:
                        async with SessionLocal() as db:
                            row = await db.get(TradeExecutor, eid, with_for_update=True)
                            if row:
                                row.status = "COMPLETED"; row.next_run_at = None; await db.commit()
                        continue
                    qty = float(sl["quantity"])
                    side = str(cfg.get("side", "buy"))
                    if not await refresh_lock(lock_key, ttl_seconds=180):
                        continue
                    execution = await execute_signal(
                        symbol, side, qty, price,
                        {"executor_id": eid, "strategy": f"executor:{cfg.get('kind','POSITION')}", "customer_id": cid, "asset": asset},
                        exchange, timeframe, df.index[-1].isoformat(), force_paper=(mode != "LIVE"),
                        stop_loss_price=cfg.get("stop_loss_price"), take_profit_price=cfg.get("take_profit_price"),
                        strategy=f"atlas-executor-{str(cfg.get('kind','POSITION')).lower()}", asset=asset, customer_id=cid,
                    )
                    actual_filled = float(execution.get("filled") or (qty if execution.get("status") == "SIMULATED" else 0.0))
                    if mode == "LIVE" and execution.get("status") in {"PROTECTION_MISSING", "UNKNOWN"}:
                        async with SessionLocal() as db:
                            row = await db.get(TradeExecutor, eid, with_for_update=True)
                            if row:
                                row.status = "STOPPED"; row.next_run_at = None; row.last_error = str(execution.get("status")); await db.commit()
                        continue
                    if actual_filled <= 0 and mode == "LIVE":
                        async with SessionLocal() as db:
                            row = await db.get(TradeExecutor, eid, with_for_update=True)
                            if row:
                                row.last_error = "No live fill confirmed; executor did not advance progress"
                                row.last_run_at = now; row.next_run_at = now + __import__("datetime").timedelta(seconds=60); await db.commit()
                        continue
                    async with SessionLocal() as db:
                        row = await db.get(TradeExecutor, eid, with_for_update=True)
                        if row:
                            row.executed_quantity = min(float(row.target_quantity or 0), float(row.executed_quantity or 0) + actual_filled)
                            row.last_run_at = now
                            row.next_run_at = now + __import__("datetime").timedelta(seconds=max(1, int(cfg.get("interval_seconds", 60))))
                            if row.executed_quantity + 1e-12 >= row.target_quantity:
                                row.status = "COMPLETED"; row.next_run_at = None
                            row.last_error = ""
                            await db.commit()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    async with SessionLocal() as db:
                        row = await db.get(TradeExecutor, eid, with_for_update=True)
                        if row:
                            row.last_error = str(exc)[:2000]; row.last_run_at = now; row.next_run_at = now + __import__("datetime").timedelta(seconds=60); await db.commit()
                finally:
                    await release_lock(lock_key)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _audit("EXECUTOR_CONTROLLER_FAILED", {"error": str(exc)})
        await asyncio.sleep(max(5, int(settings.adaptive_bot_poll_seconds)))


async def _trade_learning_replay_loop():
    """Turn completed trading episodes into persistent post-trade market memory.

    This loop is strictly post-trade: future bars are used only after an episode is
    completed, and replay results never feed directly into the same decision that created
    the trade. They become bounded research inputs for subsequent router decisions.
    """
    poll = max(30, int(settings.trade_learning_poll_seconds))
    while True:
        try:
            result = await process_trade_learning_episodes(
                limit=settings.trade_learning_max_episodes_per_cycle,
                lookback_days=settings.trade_learning_lookback_days,
            )
            if result.get("processed") or result.get("failed") or result.get("skipped"):
                await _audit("TRADE_LEARNING_REPLAY_CYCLE", result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _audit("TRADE_LEARNING_REPLAY_FAILED", {"error": str(exc)})
        await asyncio.sleep(poll)


async def _daily_research_loop():
    """Run one autonomous research cycle per UTC day, protected by a distributed Redis lock."""
    from datetime import timedelta
    while True:
        now = datetime.now(timezone.utc)
        target = now.replace(hour=max(0, min(23, settings.daily_research_hour_utc)),
                             minute=max(0, min(59, settings.daily_research_minute_utc)),
                             second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep(max(5, (target - now).total_seconds()))
        try:
            result = await run_daily_research()
            status = result.get("status")
            payload = {
                "status": status,
                "symbols": result.get("symbols_requested", []),
                "real_money_execution": False,
                "drift_flags": {r.get("symbol"): ((r.get("review") or {}).get("run_drift") or {}).get("flags", [])
                                for r in result.get("runs", []) if r.get("review")},
            }
            if status == "SKIPPED_NO_DISTRIBUTED_LOCK_BACKEND":
                # This is not a normal day's outcome: the job never even attempted to run.
                # Give it its own event name so it can't be mistaken for a real completion
                # by anyone monitoring audit event *types* rather than reading payloads.
                await _audit("RESEARCH_DAILY_MISCONFIGURED", payload)
            elif status == "ALREADY_RUNNING":
                await _audit("RESEARCH_DAILY_SKIPPED", payload)
            else:
                await _audit("RESEARCH_DAILY_COMPLETED", payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _audit("RESEARCH_DAILY_FAILED", {"error": str(exc)})


async def _usdt_tron_monitor_loop():
    """Reconcile confirmed TRC-20 USDT deposits into customer ledgers.

    The cursor is explicitly stored in milliseconds (TRON ``block_timestamp`` units).
    Each wallet is isolated so one bad wallet/API response cannot stop the remaining
    customer wallets. The per-wallet Redis lock prevents duplicate scans across workers.
    """
    import httpx
    poll_seconds = max(15, settings.usdt_tron_poll_seconds)
    overlap_ms = max(0, int(settings.usdt_tron_cursor_overlap_seconds)) * 1000
    while True:
        try:
            async with SessionLocal() as db:
                wallets = (await db.execute(select(Wallet).where(
                    Wallet.currency == "USDT", Wallet.network == "TRON", Wallet.status == "ACTIVE"))).scalars().all()
            wallets = [w for w in wallets if w.deposit_address]
            headers = {"accept": "application/json", "TRON-PRO-API-KEY": settings.usdt_trongrid_api_key}
            async with httpx.AsyncClient(timeout=15.0) as client:
                for wallet in wallets:
                    lock_key = f"tron-deposit-scan:{wallet.id}"
                    if not await acquire_lock(lock_key, ttl_seconds=max(120, poll_seconds + 120)):
                        continue
                    try:
                        async with SessionLocal() as db:
                            cursor = (await db.execute(select(TronDepositCursor).where(
                                TronDepositCursor.wallet_id == wallet.id).with_for_update())).scalar_one_or_none()
                            if not cursor:
                                cursor = TronDepositCursor(wallet_id=wallet.id, last_block_timestamp=0)
                                db.add(cursor)
                                await db.flush()
                            min_ts = max(0, int(cursor.last_block_timestamp or 0) - overlap_ms)
                            highest_ts = int(cursor.last_block_timestamp or 0)
                            await db.commit()

                        fingerprint = None
                        page_count = 0
                        while page_count < max(1, settings.usdt_tron_scan_pages):
                            params = {"only_confirmed": "true", "limit": "200",
                                      "contract_address": settings.usdt_tron_usdt_contract,
                                      "min_timestamp": str(min_ts), "order_by": "block_timestamp,asc"}
                            if fingerprint:
                                params["fingerprint"] = fingerprint
                            url = f"{settings.usdt_trongrid_base_url.rstrip('/')}/v1/accounts/{wallet.deposit_address}/transactions/trc20"
                            response = await client.get(url, params=params, headers=headers)
                            response.raise_for_status()
                            body = response.json()
                            items = body.get("data", []) or []
                            if not items:
                                break
                            for item in items:
                                if item.get("type") != "Transfer" or item.get("success") is False:
                                    continue
                                if str(item.get("to", "")) != wallet.deposit_address:
                                    continue
                                token = item.get("token_info") or {}
                                if str(token.get("address") or "") != settings.usdt_tron_usdt_contract:
                                    continue
                                decimals = int(token.get("decimals") or 0)
                                if decimals != 6:
                                    continue
                                raw_value = int(str(item.get("value", "0")))
                                if raw_value <= 0:
                                    continue
                                txid = str(item.get("transaction_id") or "")
                                sender = str(item.get("from") or "")
                                block_ts = int(item.get("block_timestamp") or 0)
                                if not txid or block_ts <= 0:
                                    continue
                                highest_ts = max(highest_ts, block_ts)

                                if settings.usdt_tron_verify_receipt:
                                    receipt_url = f"{settings.usdt_trongrid_base_url.rstrip('/')}/walletsolidity/gettransactioninfobyid"
                                    receipt_response = await client.post(receipt_url, json={"value": txid}, headers=headers)
                                    receipt_response.raise_for_status()
                                    receipt = receipt_response.json() or {}
                                    if str((receipt.get("receipt") or {}).get("result", "")).upper() != "SUCCESS":
                                        continue
                                    min_confirmations = max(0, int(settings.usdt_tron_min_confirmations))
                                    if min_confirmations > 0:
                                        block_number = int(receipt.get("blockNumber") or 0)
                                        if block_number <= 0:
                                            continue
                                        now_block_response = await client.post(
                                            f"{settings.usdt_trongrid_base_url.rstrip('/')}/wallet/getnowblock",
                                            headers=headers, json={})
                                        now_block_response.raise_for_status()
                                        now_block = now_block_response.json() or {}
                                        current_height = int(((now_block.get("block_header") or {}).get("raw_data") or {}).get("number") or 0)
                                        if current_height <= 0 or (current_height - block_number + 1) < min_confirmations:
                                            continue

                                amount = raw_value / 1_000_000
                                provider_ref = f"tron-usdt:{txid}:{sender}:{wallet.deposit_address}:{raw_value}:{block_ts}"
                                async with SessionLocal() as db:
                                    existing = (await db.execute(select(FundingTransaction).where(
                                        FundingTransaction.provider == "tron-usdt",
                                        FundingTransaction.provider_reference == provider_ref))).scalar_one_or_none()
                                    if existing:
                                        continue
                                    locked_wallet = (await db.execute(select(Wallet).where(Wallet.id == wallet.id).with_for_update())).scalar_one_or_none()
                                    if not locked_wallet:
                                        continue
                                    funding = FundingTransaction(
                                        customer_id=locked_wallet.customer_id, wallet_id=locked_wallet.id,
                                        provider="tron-usdt", provider_reference=provider_ref,
                                        amount=amount, currency="USDT", status="CONFIRMED",
                                        metadata_json=json.dumps({"network": "TRON", "contract": settings.usdt_tron_usdt_contract,
                                                                  "txid": txid, "from": sender, "to": wallet.deposit_address,
                                                                  "raw_value": str(raw_value), "decimals": decimals,
                                                                  "block_timestamp": block_ts, "confirmed_history": True}, separators=(",", ":")))
                                    funding.confirmed_at = datetime.now(timezone.utc)
                                    db.add(funding)
                                    await post_deposit(db, customer_id=locked_wallet.customer_id, wallet_id=locked_wallet.id,
                                                        amount=amount, provider_reference=provider_ref,
                                                        metadata={"network": "TRON", "contract": settings.usdt_tron_usdt_contract,
                                                                  "txid": txid, "from": sender, "to": wallet.deposit_address,
                                                                  "raw_value": str(raw_value), "decimals": decimals,
                                                                  "block_timestamp": block_ts})
                                    await sync_wallet_from_ledger(db, locked_wallet.customer_id, "USDT")
                                    account = (await db.execute(select(TradingAccount).where(
                                        TradingAccount.customer_id == locked_wallet.customer_id).with_for_update())).scalar_one_or_none()
                                    if account:
                                        balance = await customer_balance(db, locked_wallet.customer_id, "USDT")
                                        account.cash_equity = balance["available"] + balance["trading_reserved"]
                                        account.equity = max(0.0, account.cash_equity + account.realized_pnl + account.unrealized_pnl)
                                        account.peak_equity = max(account.peak_equity, account.equity)
                                    await db.commit()

                            meta = body.get("meta") or {}
                            next_fingerprint = meta.get("fingerprint")
                            page_count += 1
                            if not next_fingerprint or len(items) < 200:
                                break
                            fingerprint = next_fingerprint

                        async with SessionLocal() as db:
                            cursor = (await db.execute(select(TronDepositCursor).where(
                                TronDepositCursor.wallet_id == wallet.id).with_for_update())).scalar_one_or_none()
                            if cursor:
                                cursor.last_block_timestamp = max(int(cursor.last_block_timestamp or 0), highest_ts)
                                await db.commit()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        await _audit("TRON_WALLET_SCAN_FAILED", {"wallet_id": wallet.id, "error": str(exc)})
                    finally:
                        await release_lock(lock_key)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _audit("TRON_SCAN_CYCLE_FAILED", {"error": str(exc)})
        await asyncio.sleep(poll_seconds)


async def _reconciliation_loop():
    while True:
        await asyncio.sleep(max(15, settings.reconciliation_interval_seconds))
        should_crypto = settings.live_trading_enabled and bool(settings.exchange_api_key and settings.exchange_api_secret)
        should_oanda = bool(settings.oanda_account_id and settings.oanda_api_token and
                           settings.oanda_practice and settings.forex_demo_enabled)
        if not (should_crypto or should_oanda):
            continue
        if should_crypto:
            try:
                await reconcile(settings.default_exchange, settings.default_symbol)
            except Exception:
                logger.exception("reconciliation_loop: crypto reconcile failed (%s/%s)",
                                  settings.default_exchange, settings.default_symbol)
        if should_oanda:
            try:
                await reconcile("oanda")
            except Exception:
                logger.exception("reconciliation_loop: oanda reconcile failed")
        try:
            async with SessionLocal() as db:
                customer_exchanges = (await db.execute(
                    select(Trade.exchange).where(
                        Trade.customer_id.is_not(None),
                        Trade.status.in_(["PENDING", "OPEN", "PARTIAL", "UNKNOWN"]),
                    ).distinct()
                )).scalars().all()
            customer_exchanges = [str(x) for x in customer_exchanges if str(x).strip().lower() == "binance"]
            if customer_exchanges:
                await reconcile_customer_live_orders(customer_exchanges)
        except Exception:
            logger.exception("reconciliation_loop: customer live reconciliation failed")



async def _heartbeat_loop():
    while True:
        try:
            async with SessionLocal() as db:
                row = (await db.execute(select(ServiceHeartbeat).where(ServiceHeartbeat.instance_id == _instance_id).with_for_update())).scalar_one_or_none()
                if not row:
                    row = ServiceHeartbeat(instance_id=_instance_id, role=str(settings.process_role or "api"))
                    db.add(row)
                row.status = "READY"
                row.detail = "distributed-runtime"
                row.updated_at = datetime.now(timezone.utc)
                await db.commit()
        except Exception:
            logger.exception("heartbeat_loop: failed to record heartbeat for instance %s", _instance_id)
        await asyncio.sleep(max(5, settings.heartbeat_interval_seconds))


async def _withdrawal_recovery_loop():
    while True:
        await asyncio.sleep(max(15, settings.recovery_poll_seconds))
        if not settings.background_reconciliation_enabled or not settings.payout_require_reconciliation:
            continue
        try:
            async with SessionLocal() as db:
                rows = (await db.execute(select(Withdrawal).where(Withdrawal.status.in_(["UNKNOWN", "SUBMITTED"])).order_by(Withdrawal.updated_at).limit(25))).scalars().all()
            for w in rows:
                # Recovery is intentionally status-only; no blind payout retry is performed.
                await _audit("WITHDRAWAL_RECOVERY_DUE", {"id": w.id, "request_id": w.request_id, "status": w.status})
        except Exception:
            logger.exception("withdrawal_recovery_loop: failed to scan pending withdrawals")



def _tron_base58check_valid(address: str) -> bool:
    """Validate a TRON address through the reference wallet library."""
    try:
        from bip_utils import TrxAddrDecoder
        decoded = TrxAddrDecoder.DecodeAddr(str(address).strip())
        return len(decoded) == 21 and decoded[0] == 0x41
    except (ImportError, ValueError, TypeError, IndexError):
        return False


async def _supabase_request(path: str, payload: dict | None = None, method: str = "POST", access_token: str | None = None) -> dict:
    """Call the Supabase Auth REST API with a single hardened transport helper.

    External provider response bodies are never returned verbatim on errors; the caller gets a
    stable HTTP error while diagnostic details stay in structured logs.
    """
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(503, "Authentication service is not configured")
    import httpx
    url = settings.supabase_url.rstrip("/") + str(path)
    headers = {
        "apikey": settings.supabase_anon_key,
        "Content-Type": "application/json",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {str(access_token).strip()}"
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.request(method.upper(), url, headers=headers, json=payload if method.upper() != "GET" else None)
    except httpx.RequestError as exc:
        logger.warning("supabase_auth_transport_error: %s", type(exc).__name__)
        raise HTTPException(503, "Authentication service temporarily unavailable") from exc
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    if response.status_code >= 400:
        if response.status_code in {400, 401, 403}:
            detail = "Authentication request was rejected"
        elif response.status_code == 404:
            detail = "Authentication resource was not found"
        elif response.status_code == 429:
            detail = "Authentication service is rate limited"
        else:
            detail = "Authentication service temporarily unavailable"
        logger.warning("supabase_auth_http_error: status=%s path=%s code=%s", response.status_code, path, str(data.get("error") or data.get("msg") or data.get("message") or "")[:80])
        raise HTTPException(429 if response.status_code == 429 else (503 if response.status_code >= 500 else response.status_code), detail)
    return data if isinstance(data, dict) else {"data": data}


async def _supabase_user(access_token: str) -> dict:
    """Fetch the authenticated Supabase user profile using the bearer token."""
    token = str(access_token or "").strip()
    if not token:
        raise HTTPException(401, "Authentication required")
    data = await _supabase_request("/auth/v1/user", method="GET", access_token=token)
    user = data.get("user") if isinstance(data, dict) and isinstance(data.get("user"), dict) else data
    if not isinstance(user, dict) or not user.get("id"):
        raise HTTPException(401, "Invalid authenticated user")
    return user


_customer_jwks_cache: dict = {"expires": 0.0, "keys": {}}
_jwks_refresh_lock = asyncio.Lock()


async def _load_supabase_jwks(force: bool = False) -> dict:
    global _customer_jwks_cache
    async with _jwks_refresh_lock:
        now = time.time()
        if not force and now < _customer_jwks_cache["expires"]:
            return _customer_jwks_cache["keys"]
        import httpx
        jwks_url = settings.supabase_jwks_url or settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(jwks_url)
                r.raise_for_status()
                data = r.json()
                keys = {k["kid"]: k for k in data.get("keys", []) if k.get("kid")}
                if not keys:
                    raise ValueError("Supabase JWKS returned no usable keys")
        except Exception as exc:
            logger.warning("supabase_jwks_refresh_failed: %s", type(exc).__name__)
            raise HTTPException(503, "Authentication service temporarily unavailable") from exc
        _customer_jwks_cache = {"expires": now + 600, "keys": keys}
        return keys


async def _supabase_claims(access_token: str, require_aal2: bool = False) -> dict:
    """Single authoritative Supabase JWT verifier for both customer/admin flows."""
    token = str(access_token or "").strip()
    if not token or not settings.supabase_url:
        raise HTTPException(401, "Authentication required")
    import jwt
    try:
        header = jwt.get_unverified_header(token)
        token_alg = str(header.get("alg") or "")
        kid = str(header.get("kid") or "")
        if token_alg not in {"RS256", "ES256"} or not kid:
            raise HTTPException(401, "Invalid authentication token")
        keys = await _load_supabase_jwks(False)
        jwk = keys.get(kid)
        if not jwk:
            # Supabase supports key rotation; refresh once before rejecting an unknown kid.
            keys = await _load_supabase_jwks(True)
            jwk = keys.get(kid)
        if not jwk:
            raise HTTPException(401, "Invalid authentication token")
        jwk_alg = str(jwk.get("alg") or "")
        if jwk_alg and jwk_alg != token_alg:
            raise HTTPException(401, "Invalid authentication token")
        key = jwt.PyJWK(jwk).key
        claims = jwt.decode(token, key=key, algorithms=[token_alg], audience=settings.supabase_auth_audience, issuer=settings.supabase_url.rstrip("/") + "/auth/v1")
        if not claims.get("sub"):
            raise HTTPException(401, "Invalid authentication token")
        if require_aal2 and claims.get("aal", "aal1") != "aal2":
            raise HTTPException(403, "Google Authenticator verification required")
        return claims
    except HTTPException:
        raise
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid authentication token")
    except Exception:
        raise HTTPException(401, "Invalid authentication token")


async def _customer_mfa_state(authorization: str | None) -> dict:
    """Return only verified Supabase MFA factors for the authenticated customer.

    Supabase exposes factor enrollment through the authenticated user session and the JWT
    contains the current AAL claim. Only verified factors count as enrolled for AtlasRisk
    access enforcement.
    """
    token = _bearer_token(authorization)
    claims = await _supabase_claims(token, require_aal2=False)
    user = await _supabase_user(token)
    factors = user.get("factors") or []
    verified = [
        f for f in factors
        if str(f.get("factor_type") or "").lower() == "totp"
        and str(f.get("status") or "").lower() == "verified"
    ]
    return {
        "enabled": bool(verified),
        "aal": str(claims.get("aal") or "aal1"),
        "factor_count": len(verified),
        "factor_ids": [str(f.get("id")) for f in verified if f.get("id")],
    }


async def customer_claims(authorization: str | None, require_aal2: bool = True) -> dict:
    token = _bearer_token(authorization)
    claims = await _supabase_claims(token, require_aal2=False)
    if require_aal2 and settings.customer_totp_required:
        state = await _customer_mfa_state(authorization)
        if not state["enabled"]:
            raise HTTPException(403, "Google Authenticator setup is required")
        if claims.get("aal", "aal1") != "aal2":
            raise HTTPException(403, "Google Authenticator verification required")
    return claims


def _bearer_token(authorization: str | None) -> str:
    value = str(authorization or "").strip()
    if not value.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer authentication required")
    token = value.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(401, "Bearer authentication required")
    return token


async def admin_claims(authorization: str | None, require_aal2: bool = True) -> dict:
    token = _bearer_token(authorization)
    claims = await _supabase_claims(token, require_aal2=False)
    allowed = {x.strip() for x in (settings.admin_supabase_user_ids or "").split(",") if x.strip()}
    uid = str(claims.get("sub") or "")
    if uid not in allowed:
        try:
            assigned = await get_roles(uid)
        except Exception as exc:
            raise HTTPException(503, "Administrator role store is unavailable") from exc
        if not assigned:
            raise HTTPException(403, "Administrator account is not authorized")
    if require_aal2 and settings.admin_totp_required and claims.get("aal", "aal1") != "aal2":
        raise HTTPException(403, "Google Authenticator verification required for administrator access")
    _audit_actor.set(str(claims.get("sub") or "admin"))
    return claims


async def auth(x_admin_token: str | None = None, authorization: str | None = None):
    """Authenticate privileged APIs; the legacy shared token is development-only."""
    if authorization and authorization.strip():
        return await admin_claims(authorization, require_aal2=settings.admin_totp_required)
    if str(settings.environment).lower() != "development":
        raise HTTPException(401, "Administrator authentication requires Supabase Auth with MFA outside development")
    configured = str(settings.admin_token or "").strip()
    supplied = str(x_admin_token or "").strip()
    if not configured or not supplied or not hmac.compare_digest(supplied, configured):
        raise HTTPException(401, "Administrator authentication required")
    _audit_actor.set("legacy-admin-token")
    return {"auth_method": "legacy_admin_token"}


def approver_auth(admin_id: str, approver_token: str | None, admin_token: str | None = None):
    admin_id = str(admin_id or "").strip()
    token = str(approver_token or "").strip()
    if not admin_id or not token:
        raise HTTPException(401, "Distinct withdrawal approver credentials are required")
    pairs = {}
    for item in str(settings.withdrawal_approver_tokens or "").split(","):
        if ":" not in item:
            continue
        key, secret = item.split(":", 1)
        if key.strip() and secret.strip():
            pairs[key.strip()] = secret.strip()
    expected = pairs.get(admin_id)
    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(403, "Invalid withdrawal approver credentials")
    if admin_token and hmac.compare_digest(token, str(admin_token)):
        raise HTTPException(403, "Approver credential must be distinct from administrator credential")
    return True


async def get_customer(authorization: str | None, db, require_aal2: bool = True):
    claims = await customer_claims(authorization, require_aal2=require_aal2)
    uid = claims["sub"]
    profile = (await db.execute(select(CustomerProfile).where(CustomerProfile.auth_user_id == uid))).scalar_one_or_none()
    email = str(claims.get("email") or "")[:320]
    name = str((claims.get("user_metadata") or {}).get("full_name") or (claims.get("user_metadata") or {}).get("name") or "")[:160]
    if not profile:
        # Concurrent first requests can both observe no profile. Use a savepoint so
        # the unique auth_user_id constraint resolves the loser without poisoning
        # the caller's transaction.
        try:
            async with db.begin_nested():
                profile = CustomerProfile(auth_user_id=uid, email=email, display_name=name, status="ACTIVE")
                db.add(profile)
                await db.flush()
        except IntegrityError:
            profile = (await db.execute(select(CustomerProfile).where(CustomerProfile.auth_user_id == uid))).scalar_one_or_none()
            if not profile:
                raise
    if profile.status != "ACTIVE":
        raise HTTPException(403, "Customer account is not active")
    await _ensure_customer_subscription(db, profile)
    return profile, claims


def _funding_signature_valid(raw_body: bytes, signature: str | None) -> bool:
    if not settings.funding_webhook_secret or not signature:
        return False
    expected = hmac.new(settings.funding_webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    supplied = signature.removeprefix("sha256=").strip()
    return hmac.compare_digest(expected, supplied)

def _normalize_oanda_instrument(symbol: str) -> str:
    raw = str(symbol or "").strip().upper().replace("/", "_").replace("-", "_")
    aliases = {
        "EURUSD":"EUR_USD", "GBPUSD":"GBP_USD", "USDJPY":"USD_JPY", "USDCHF":"USD_CHF",
        "AUDUSD":"AUD_USD", "USDCAD":"USD_CAD", "NZDUSD":"NZD_USD",
        "XAUUSD":"XAU_USD", "XAGUSD":"XAG_USD", "WTI":"WTICO_USD", "WTI_USD":"WTICO_USD",
        "BRENT":"BCO_USD", "BRENT_USD":"BCO_USD", "NATGAS":"NATGAS_USD",
    }
    return aliases.get(raw, raw)


def _oanda_credentials_for_customer(customer_id: int | None):
    if customer_id is None:
        return settings.oanda_account_id, settings.oanda_api_token, settings.oanda_practice
    raise RuntimeError("Customer OANDA credentials must be resolved from the customer account mapping")


def _assert_established_noncrypto(req):
    if req.asset == "forex" and settings.adaptive_require_established_noncrypto:
        allowed = {x.strip().upper() for x in settings.adaptive_established_fx_symbols.split(",") if x.strip()}
        if _normalize_oanda_instrument(req.symbol) not in allowed:
            raise HTTPException(400, "FX bot is limited to the configured major currency universe")
    if req.asset == "commodity" and settings.adaptive_require_established_noncrypto:
        allowed = {x.strip().upper() for x in settings.adaptive_established_commodity_symbols.split(",") if x.strip()}
        if _normalize_oanda_instrument(req.symbol) not in allowed:
            raise HTTPException(400, "Commodity bot is limited to the configured established instrument universe")


def market_data(req, customer_id: int | None = None):
    if req.asset == "crypto":
        return fetch_crypto(req.symbol, req.exchange, req.timeframe, req.days, closed_only=True)
    symbol = _normalize_oanda_instrument(req.symbol)
    if customer_id is not None:
        raise RuntimeError("customer-scoped OANDA data must be loaded by the async customer controller")
    if settings.forex_broker == "oanda" and settings.oanda_account_id and settings.oanda_api_token:
        return fetch_forex_oanda(symbol, req.timeframe, req.days)
    return fetch_forex(req.symbol, req.timeframe, req.days)




def _market_data_quality(df, timeframe: str, asset: str = "crypto") -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if df is None or len(df) < settings.min_bars:
        reasons.append("insufficient_bars")
        return False, reasons
    # Crypto-specific liquidity/established-universe checks are intentionally not applied to FX/commodities.
    if asset == "crypto" and settings.adaptive_require_established_crypto:
        try:
            established = {x.strip().upper() for x in settings.adaptive_established_symbols.split(",") if x.strip()}
            normalized_symbol = str(getattr(df, "attrs", {}).get("symbol", ""))
            # Symbol allowlisting is enforced at request level below; volume remains a second independent gate.
            if normalized_symbol and normalized_symbol.upper() not in established:
                reasons.append("symbol_not_in_established_universe")
            if "volume" not in df.columns:
                reasons.append("missing_volume_for_liquidity_gate")
            else:
                tf_seconds = max(60.0, pd.Timedelta(timeframe).total_seconds())
                bars_24h = max(1, int(round(86400.0 / tf_seconds)))
                quote_volume_24h = float((df["close"].astype(float) * df["volume"].astype(float)).tail(bars_24h).sum())
                if quote_volume_24h < settings.adaptive_min_quote_volume_24h_usd:
                    reasons.append("market_liquidity_below_established_threshold")
        except Exception:
            reasons.append("liquidity_gate_unavailable")
    if not getattr(df.index, "is_monotonic_increasing", False):
        reasons.append("timestamps_not_monotonic")
    if df.index.has_duplicates:
        reasons.append("duplicate_timestamps")
    last = df.index[-1]
    try:
        age = (datetime.now(timezone.utc) - last.to_pydatetime()).total_seconds()
        tf = pd.Timedelta(timeframe).total_seconds()
        # Completed-bar data is expected to be no older than 3 bars or the configured hard ceiling.
        allowed = min(float(settings.stale_data_minutes * 60), max(60.0, tf * 3.5))
        if age > allowed:
            reasons.append("stale_market_data")
    except Exception:
        reasons.append("invalid_market_timestamp")
    return not reasons, reasons


async def _customer_oanda_spread_bps(customer_id: int, symbol: str) -> float | None:
    async with SessionLocal() as cdb:
        row = (await cdb.execute(select(CustomerOandaAccount).where(CustomerOandaAccount.customer_id == customer_id))).scalar_one_or_none()
    broker = build_customer_oanda_broker(row, timeout_seconds=settings.oanda_timeout_seconds)
    try:
        ticker = await asyncio.to_thread(broker.ticker, _normalize_oanda_instrument(symbol))
        bid, ask = float(ticker.get("bid") or 0), float(ticker.get("ask") or 0)
        if bid <= 0 or ask <= 0 or ask < bid:
            raise RuntimeError("OANDA quote has no valid bid/ask")
        return (ask - bid) / ((ask + bid) / 2) * 10_000
    finally:
        broker.close()


def _current_spread_bps(req: MarketRequest, customer_id: int | None = None) -> float | None:
    if req.asset == "crypto":
        import ccxt
        if req.exchange not in ccxt.exchanges:
            raise RuntimeError(f"Unsupported CCXT exchange: {req.exchange}")
        ex = getattr(ccxt, req.exchange)({"enableRateLimit": True})
        try:
            ex.load_markets()
            ticker = ex.fetch_ticker(req.symbol)
            bid = float(ticker.get("bid") or 0)
            ask = float(ticker.get("ask") or 0)
            if bid <= 0 or ask <= 0 or ask < bid:
                raise RuntimeError("Market quote has no valid bid/ask")
            return (ask - bid) / ((ask + bid) / 2) * 10_000
        finally:
            if hasattr(ex, "close") and callable(ex.close):
                ex.close()
    if customer_id is not None and req.asset in {"forex", "commodity"}:
        async def _get_customer_broker():
            async with SessionLocal() as cdb:
                row = (await cdb.execute(select(CustomerOandaAccount).where(CustomerOandaAccount.customer_id == customer_id))).scalar_one_or_none()
            return build_customer_oanda_broker(row, timeout_seconds=settings.oanda_timeout_seconds)
        # This function is normally called through asyncio.to_thread; customer-specific OANDA
        # quote retrieval is handled by the autonomous caller before live execution.
        return None
    if settings.oanda_account_id and settings.oanda_api_token:
        broker = __import__("app.forex_oanda", fromlist=["OandaBroker", "OandaConfig"]).OandaBroker(
            __import__("app.forex_oanda", fromlist=["OandaBroker", "OandaConfig"]).OandaConfig(
                settings.oanda_account_id, settings.oanda_api_token, settings.oanda_practice, settings.oanda_timeout_seconds))
        try:
            ticker = broker.ticker(_normalize_oanda_instrument(req.symbol))
            bid, ask = float(ticker.get("bid") or 0), float(ticker.get("ask") or 0)
            if bid <= 0 or ask <= 0 or ask < bid:
                raise RuntimeError("OANDA quote has no valid bid/ask")
            return (ask - bid) / ((ask + bid) / 2) * 10_000
        finally:
            broker.close()
    return None


async def _get_or_create_customer_trading_account(db, profile: CustomerProfile) -> TradingAccount:
    account = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == profile.id).with_for_update())).scalar_one_or_none()
    wallet = (await db.execute(select(Wallet).where(Wallet.customer_id == profile.id, Wallet.currency == "USDT").with_for_update())).scalar_one_or_none()
    if not wallet or wallet.status != "ACTIVE":
        raise HTTPException(409, "Fund the USDT trading wallet before starting the bot")
    ledger = await get_or_create_ledger(db, profile.id, "USDT")
    # Legacy wallets are migrated once into the authoritative ledger balance. New credits only enter through ledger postings.
    if float(ledger.available) == 0 and float(ledger.trading_reserved) == 0 and float(wallet.available_balance) > 0:
        ledger.available = float(wallet.available_balance)
        wallet.available_balance = float(ledger.available)
    if float(ledger.available) + float(ledger.trading_reserved) <= 0:
        raise HTTPException(409, "Fund the USDT trading wallet before starting the bot")
    await sync_wallet_from_ledger(db, profile.id, "USDT")
    total_capital = float(ledger.available) + float(ledger.trading_reserved)
    if not account:
        account = TradingAccount(customer_id=profile.id, currency="USDT", status="ACTIVE",
                                 cash_equity=total_capital, equity=total_capital, peak_equity=total_capital,
                                 daily_start_equity=total_capital, daily_start_date=datetime.now(timezone.utc).date(),
                                 reserved_margin=float(ledger.trading_reserved))
        db.add(account)
        await db.flush()
    elif account.status != "ACTIVE":
        raise HTTPException(409, "Customer trading account is not active")
    account.cash_equity = total_capital
    account.reserved_margin = float(ledger.trading_reserved)
    return account


def _safe_model_component(value: str) -> str:
    raw = str(value or "")
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-") or "value"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"{clean[:50]}-{digest}"


def model_file(req):
    # Request fields are user-controlled. Sanitize every path component and add a
    # stable hash so model endpoints cannot escape MODEL_DIR via path traversal.
    safe_asset = _safe_model_component(req.asset)
    safe_exchange = _safe_model_component(req.exchange)
    safe_symbol = _safe_model_component(req.symbol)
    safe_timeframe = _safe_model_component(req.timeframe)
    return str(Path(settings.model_dir) / f"{safe_asset}_{safe_exchange}_{safe_symbol}_{safe_timeframe}.joblib")


class MarketRequest(BaseModel):
    asset: str = Field(default="crypto", pattern="^(crypto|forex|commodity)$")
    symbol: str = "BTC/USDT:USDT"
    exchange: str = "binance"
    timeframe: str = "1h"
    days: int = Field(default=365, ge=30, le=1500)


class CustomerBotStartRequest(MarketRequest):
    risk_fraction: float | None = Field(default=None, gt=0, le=0.02)
    autonomous: bool = True
    interval_seconds: int = Field(default=900, ge=60, le=86400)
    strategy_candidate_id: int | None = Field(default=None, gt=0)


class SmartTradeRequest(BaseModel):
    symbol: str = Field(min_length=2, max_length=80)
    exchange: str = Field(default="bybit", min_length=2, max_length=50)
    side: str = Field(pattern="^(BUY|SELL)$")
    entry_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    stop_loss_price: float = Field(gt=0)
    take_profit_1: float = Field(gt=0)
    take_profit_2: float = Field(default=0, ge=0)
    take_profit_3: float = Field(default=0, ge=0)
    trailing_stop_pct: float = Field(default=0, ge=0, le=20)
    breakeven_at_r: float = Field(default=1.0, ge=0, le=10)
    notes: str = Field(default="", max_length=1000)


class DcaBotRequest(BaseModel):
    symbol: str = Field(min_length=2, max_length=80)
    exchange: str = Field(default="bybit", min_length=2, max_length=50)
    side: str = Field(default="LONG", pattern="^(LONG|SHORT)$")
    initial_quote: float = Field(gt=0)
    safety_order_quote: float = Field(gt=0)
    max_safety_orders: int = Field(default=3, ge=1, le=20)
    deviation_pct: float = Field(default=1.0, gt=0, le=50)
    volume_scale: float = Field(default=1.5, ge=1, le=5)
    step_scale: float = Field(default=1.25, ge=1, le=5)
    take_profit_pct: float = Field(default=2.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=5.0, gt=0, le=100)
    trailing_take_profit_pct: float = Field(default=0, ge=0, le=50)


class AlertRequest(BaseModel):
    alert_type: str = Field(default="PRICE", pattern="^(PRICE|TRADE|RISK|SYSTEM)$")
    symbol: str = Field(default="", max_length=80)
    threshold: float = Field(default=0, ge=0)
    condition: str = Field(default="ABOVE", pattern="^(ABOVE|BELOW|CROSSES)$")
    channel: str = Field(default="IN_APP", pattern="^(IN_APP|EMAIL)$")
    message: str = Field(default="", max_length=500)


class StrategyLabRequest(BaseModel):
    name: str = Field(default="Atlas Candidate", min_length=2, max_length=120)
    prompt: str = Field(min_length=20, max_length=4000)
    asset: str = Field(default="crypto", pattern="^(crypto|forex|commodity)$")
    symbol: str = Field(default="BTC/USDT:USDT", min_length=2, max_length=80)
    exchange: str = Field(default="binance", min_length=2, max_length=50)
    timeframe: str = Field(default="1h", pattern="^(5m|15m|30m|1h|4h|1d)$")
    days: int = Field(default=365, ge=60, le=1500)

class ExecutorCreateRequest(BaseModel):
    kind: str = Field(pattern="^(POSITION|DCA|TWAP)$")
    asset: str = Field(default="crypto", pattern="^(crypto|forex|commodity)$")
    symbol: str = Field(min_length=2, max_length=80)
    exchange: str = Field(default="binance", min_length=2, max_length=50)
    timeframe: str = Field(default="1h")
    side: str = Field(pattern="^(buy|sell)$")
    total_quantity: float = Field(gt=0)
    slices: int = Field(default=1, ge=1, le=200)
    interval_seconds: int = Field(default=60, ge=1, le=86400)
    max_slippage_bps: float = Field(default=25, ge=0, le=500)
    stop_loss_price: float | None = Field(default=None, gt=0)
    take_profit_price: float | None = Field(default=None, gt=0)
    mode: str = Field(default="PAPER", pattern="^(PAPER|LIVE)$")

class StrategyBuilderRequest(BaseModel):
    prompt: str = Field(min_length=20, max_length=4000)
    name: str = Field(default="Atlas AI Strategy", min_length=2, max_length=120)
    # Market fields are optional and default to the Strategy Lab defaults so existing
    # clients that only send prompt/name keep working.
    asset: str = Field(default="crypto", pattern="^(crypto|forex|commodity)$")
    symbol: str = Field(default="BTC/USDT:USDT", min_length=2, max_length=80)
    exchange: str = Field(default="binance", min_length=2, max_length=50)
    timeframe: str = Field(default="1h", pattern="^(5m|15m|30m|1h|4h|1d)$")


class GridBotRequest(BaseModel):
    symbol: str = Field(min_length=2, max_length=80)
    exchange: str = Field(default="bybit", min_length=2, max_length=50)
    grid_type: str = Field(default="NEUTRAL", pattern="^(LONG|NEUTRAL|SHORT)$")
    lower_price: float = Field(gt=0)
    upper_price: float = Field(gt=0)
    levels: int = Field(default=20, ge=2, le=200)
    arithmetic: bool = False
    quote_per_grid: float = Field(gt=0)
    take_profit_pct: float = Field(default=0, ge=0, le=100)
    stop_loss_pct: float = Field(default=0, ge=0, le=100)
    trailing_stop_pct: float = Field(default=0, ge=0, le=50)


class WebhookCreateRequest(BaseModel):
    name: str = Field(default="TradingView", min_length=2, max_length=100)


class ConnectorTestRequest(BaseModel):
    exchange: str = Field(min_length=2, max_length=50)
    market_type: str = Field(default="spot", pattern="^(spot|swap|future)$")


class ArbitrageLeg(BaseModel):
    symbol: str = Field(min_length=2, max_length=80)
    side: str = Field(pattern="^(BUY|SELL)$")
    base_asset: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    quote_asset: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    bid_qty: float = Field(default=0, ge=0)
    ask_qty: float = Field(default=0, ge=0)


class DerivPreflightRequest(BaseModel):
    currency: str | None = Field(default=None, max_length=10)


class DerivConnectRequest(BaseModel):
    account_id: str = Field(min_length=3, max_length=80)
    api_token: str = Field(min_length=20, max_length=1024)


class DerivTradeRequest(BaseModel):
    contract_type: str = Field(min_length=2, max_length=40)
    underlying_symbol: str = Field(min_length=2, max_length=40)
    amount: float = Field(gt=0)
    duration: int | None = Field(default=None, gt=0, le=86400)
    duration_unit: str | None = Field(default=None, max_length=4)
    basis: str = Field(default="stake", pattern="^(stake|payout)$")
    contract_category: str | None = Field(default=None, max_length=30)
    barrier: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, max_length=10)


class BinanceArbitrageLiveRequest(BaseModel):
    legs: list[ArbitrageLeg] = Field(min_length=3, max_length=3)
    start_quote: float = Field(gt=0)
    start_asset: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    confirmation: str = Field(default="", max_length=64)


class ArbitragePaperRequest(BaseModel):
    legs: list[ArbitrageLeg] = Field(min_length=3, max_length=3)
    start_quote: float = Field(gt=0)
    start_asset: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")


class ExecutionPlanRequest(BaseModel):
    side: str = Field(pattern="^(buy|sell)$")
    quantity: float = Field(gt=0)
    best_price: float = Field(gt=0)
    levels: list[dict[str, float]] = Field(min_length=1, max_length=100)
    maker_fee_bps: float = Field(default=0, ge=0, le=500)
    taker_fee_bps: float = Field(default=0, ge=0, le=500)
    latency_ms: float = Field(default=0, ge=0, le=60000)
    short_term_vol_bps_per_s: float = Field(default=0, ge=0, le=10000)
    max_adverse_bps: float = Field(default=50, gt=0, le=5000)
    urgency: float = Field(default=0.5, ge=0, le=1)


class BotActionRequest(BaseModel):
    action: str = Field(pattern="^(START|STOP)$")


class TrainRequest(MarketRequest):
    min_train: int = Field(default=800, ge=200, le=5000)
    folds: int = Field(default=5, ge=2, le=10)


class ExecuteRequest(MarketRequest):
    side: str = Field(pattern="^(buy|sell)$")
    quantity: float = Field(gt=0)
    price: float = Field(default=0, ge=0)
    score: float = 0.0
    long_probability: float = 0.0
    short_probability: float = 0.0
    flat_probability: float = 0.0
    signal_timestamp: str | None = None
    request_id: str | None = Field(default=None, min_length=8, max_length=80)
    force_paper: bool = True
    stop_loss_price: float | None = Field(default=None, gt=0)
    take_profit_price: float | None = Field(default=None, gt=0)
    strategy: str = "manual-v1"
    demo_forex: bool = False


class LiveEnableRequest(BaseModel):
    confirmation: str


class WithdrawalCreate(BaseModel):
    request_id: str = Field(min_length=3, max_length=120)
    account_ref: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0)
    currency: str = Field(min_length=2, max_length=20)
    destination_masked: str = Field(min_length=3, max_length=180)
    risk_score: float = Field(default=0.0, ge=0, le=1)
    risk_flags: list[str] = Field(default_factory=list, max_length=20)
    destination: str | None = Field(default=None, min_length=3, max_length=500)
    destination_tag: str | None = Field(default=None, max_length=120)
    network: str | None = Field(default=None, max_length=40)
    provider: str = Field(default="", max_length=40)


class CustomerWithdrawalCreate(BaseModel):
    amount: float = Field(gt=0)
    destination: str = Field(min_length=30, max_length=50)
    destination_tag: str | None = Field(default=None, max_length=120)
    network: str = Field(default="TRON", min_length=3, max_length=40)


class WithdrawalDecision(BaseModel):
    admin_id: str = Field(min_length=2, max_length=120)
    reason: str = Field(default="", max_length=500)


class WithdrawalExecuteRequest(BaseModel):
    operator_id: str = Field(min_length=2, max_length=120)
    signature: str | None = None


class WithdrawalReconcileRequest(BaseModel):
    operator_id: str = Field(min_length=2, max_length=120)


class ModelRollbackRequest(BaseModel):
    asset: str = Field(default="crypto", pattern="^(crypto|forex|commodity)$")
    symbol: str = Field(default="BTC/USDT:USDT", min_length=3, max_length=80)
    exchange: str = Field(default="binance", min_length=2, max_length=50)
    timeframe: str = Field(default="1h", min_length=2, max_length=10)


PLAN_DEFINITIONS = {
    "free": {"name": "Atlas Free", "monthly": 0.0, "annual": 0.0, "ai_credits": 100, "exchanges": 0, "strategies": 0, "live": False, "paper": True, "features": ["market_analysis", "paper_trading", "basic_backtesting"]},
    "starter": {"name": "Atlas Starter", "monthly": 7.99, "annual": 79.90, "ai_credits": 1000, "exchanges": 1, "strategies": 1, "live": True, "paper": True, "features": ["market_analysis", "paper_trading", "backtesting", "automated_entry_exit", "daily_research", "smart_trade", "market_scanner", "alerts","grid_bot", "arbitrage"]},
    "pro": {"name": "Atlas Pro", "monthly": 17.99, "annual": 179.90, "ai_credits": 5000, "exchanges": 3, "strategies": 5, "live": True, "paper": True, "features": ["advanced_ai", "daily_research", "multi_timeframe", "risk_engine", "portfolio_analytics", "automated_entry_exit", "dca_bot", "smart_trade", "market_scanner", "alerts", "trading_journal","grid_bot", "arbitrage"]},
    "elite": {"name": "Atlas Elite", "monthly": 39.99, "annual": 399.90, "ai_credits": 20000, "exchanges": 10, "strategies": 20, "live": True, "paper": True, "features": ["advanced_ai", "daily_research", "walk_forward", "portfolio_risk", "api_access", "priority_support", "dca_bot", "smart_trade", "market_scanner", "alerts", "trading_journal", "strategy_builder", "webhooks", "grid_bot", "arbitrage"]},
}


def _plan_price(code: str, interval: str) -> float:
    d = PLAN_DEFINITIONS.get(code)
    if not d or code == "free":
        return 0.0
    return float(d["annual"] if interval == "annual" else d["monthly"])


async def _ensure_billing_plans(db):
    for code, d in PLAN_DEFINITIONS.items():
        row = (await db.execute(select(Plan).where(Plan.code == code))).scalar_one_or_none()
        if not row:
            db.add(Plan(code=code, name=d["name"], monthly_price=d["monthly"], annual_price=d["annual"], ai_credits=d["ai_credits"], exchange_connections=d["exchanges"], active_strategies=d["strategies"], live_trading=d["live"], paper_trading=d["paper"], features_json=json.dumps(d["features"])))
        else:
            row.name=d["name"]; row.monthly_price=d["monthly"]; row.annual_price=d["annual"]; row.ai_credits=d["ai_credits"]; row.exchange_connections=d["exchanges"]; row.active_strategies=d["strategies"]; row.live_trading=d["live"]; row.paper_trading=d["paper"]; row.features_json=json.dumps(d["features"])
    await db.flush()


async def _get_active_subscription(db, customer_id: int):
    sub = (await db.execute(select(Subscription).where(Subscription.customer_id == customer_id, Subscription.status.in_(["trialing", "active", "past_due"])).order_by(desc(Subscription.created_at)).limit(1))).scalar_one_or_none()
    if sub and sub.status == "trialing" and sub.trial_end and sub.trial_end <= datetime.now(timezone.utc):
        sub.status = "active"
        sub.plan_code = "free"
        sub.current_period_start = datetime.now(timezone.utc)
        sub.current_period_end = datetime.now(timezone.utc)
        await db.flush()
    return sub


async def _ensure_customer_subscription(db, profile: CustomerProfile, referral_code: str | None = None):
    await _ensure_billing_plans(db)
    sub = await _get_active_subscription(db, profile.id)
    if sub:
        return sub
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    trial_end = now + timedelta(days=max(0, settings.billing_trial_days))
    try:
        async with db.begin_nested():
            sub = Subscription(customer_id=profile.id, plan_code="pro" if settings.billing_trial_days else "free", billing_interval="monthly", status="trialing" if settings.billing_trial_days else "active", provider="internal", provider_subscription_id=f"atlas-free-{profile.id}", current_period_start=now, current_period_end=trial_end, trial_end=trial_end)
            db.add(sub)
            await db.flush()
    except IntegrityError:
        sub = (await db.execute(select(Subscription).where(Subscription.provider_subscription_id == f"atlas-free-{profile.id}").with_for_update())).scalar_one_or_none()
        if not sub:
            raise
    code = (referral_code or "").strip().upper()
    if code:
        rc = (await db.execute(select(ReferralCode).where(ReferralCode.code == code, ReferralCode.active == True))).scalar_one_or_none()
        if rc and rc.customer_id != profile.id:
            existing = (await db.execute(select(Referral).where(Referral.referred_customer_id == profile.id))).scalar_one_or_none()
            if not existing:
                db.add(Referral(referral_code=code, referrer_customer_id=rc.customer_id, referred_customer_id=profile.id, status="PENDING"))
    return sub


async def _subscription_entitlements(db, customer_id: int):
    sub = await _get_active_subscription(db, customer_id)
    if not sub:
        return PLAN_DEFINITIONS["free"], None
    d = PLAN_DEFINITIONS.get(sub.plan_code, PLAN_DEFINITIONS["free"])
    return d, sub


class PlanChangeRequest(BaseModel):
    plan: str = Field(pattern="^(free|starter|pro|elite)$")
    interval: str = Field(default="monthly", pattern="^(monthly|annual)$")


class ReferralCodeRequest(BaseModel):
    code: str | None = Field(default=None, min_length=4, max_length=40)


class CostEventRequest(BaseModel):
    customer_id: int | None = None
    category: str = Field(min_length=2, max_length=40)
    provider: str = Field(default="", max_length=60)
    amount: float = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=10)
    reference: str = Field(default="", max_length=180)


class RevenueEventRequest(BaseModel):
    customer_id: int | None = None
    subscription_id: int | None = None
    provider: str = Field(default="manual", max_length=30)
    provider_reference: str = Field(min_length=2, max_length=180)
    gross_amount: float = Field(ge=0)
    refunds: float = Field(default=0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=10)


async def _stripe_checkout(plan: str, interval: str, customer_email: str, customer_id: int, referral_discount: bool = False):
    if not settings.stripe_enabled or not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe billing is not configured")
    price_map = {("starter","monthly"): settings.stripe_price_starter_monthly, ("pro","monthly"): settings.stripe_price_pro_monthly, ("elite","monthly"): settings.stripe_price_elite_monthly, ("starter","annual"): settings.stripe_price_starter_annual, ("pro","annual"): settings.stripe_price_pro_annual, ("elite","annual"): settings.stripe_price_elite_annual}
    price_id = price_map.get((plan, interval), "")
    if not price_id:
        raise HTTPException(503, "Stripe price is not configured for this plan")
    import httpx
    headers={"Authorization": f"Bearer {settings.stripe_secret_key}"}
    data={"mode":"subscription","line_items[0][price]":price_id,"line_items[0][quantity]":"1","customer_email":customer_email,"client_reference_id":str(customer_id),"metadata[atlas_customer_id]":str(customer_id),"metadata[atlas_plan]":plan,"metadata[atlas_interval]":interval,"success_url":"/billing/success","cancel_url":"/billing/cancel"}
    if referral_discount and settings.stripe_referral_coupon_id:
        data["discounts[0][coupon]"] = settings.stripe_referral_coupon_id
    async with httpx.AsyncClient(timeout=20) as client:
        r=await client.post("https://api.stripe.com/v1/checkout/sessions",headers=headers,data=data)
    if r.status_code >= 400:
        raise HTTPException(502, "Payment provider could not create checkout session")
    return r.json()


@app.get("/", response_class=HTMLResponse)
async def customer_portal(request: Request):
    return templates.TemplateResponse(request, "customer.html", {"settings": settings})


class BinanceSubAccountProvisionRequest(BaseModel):
    customer_id: int = Field(gt=0)
    tag: str = Field(min_length=1, max_length=31)


class AdminLoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)


@app.post("/api/admin/auth/login")
async def admin_auth_login(req: AdminLoginRequest):
    """Authenticate an allow-listed admin with Supabase; TOTP is then required for AAL2."""
    key = hashlib.sha256(req.email.strip().lower().encode()).hexdigest()
    allowed, _ = await allow_rate_limit(f"admin-login:account:{key}", max(1, settings.auth_rate_limit_per_minute))
    if not allowed:
        raise HTTPException(429, "Administrator login rate limit exceeded")
    result = await _supabase_request("/auth/v1/token?grant_type=password", payload={"email": req.email, "password": req.password})
    access_token = str(result.get("access_token") or "")
    if not access_token:
        raise HTTPException(401, "Administrator login failed")
    claims = await _supabase_claims(access_token, require_aal2=False)
    allowed = {x.strip() for x in (settings.admin_supabase_user_ids or "").split(",") if x.strip()}
    if not allowed or claims["sub"] not in allowed:
        raise HTTPException(403, "Administrator account is not authorized")
    user = await _supabase_user(access_token)
    factors = user.get("factors") or []
    verified_totp = [f for f in factors if f.get("factor_type") == "totp" and f.get("status") == "verified"]
    return {
        "ok": True, "access_token": access_token, "refresh_token": result.get("refresh_token"),
        "expires_in": result.get("expires_in"), "user_id": claims["sub"],
        "mfa_required": settings.admin_totp_required, "totp_enrolled": bool(verified_totp),
        "aal": claims.get("aal", "aal1"),
        "message": "Enter the 6-digit Google Authenticator code to complete administrator sign-in." if settings.admin_totp_required else "Administrator sign-in complete."
    }


@app.get("/api/admin/auth/mfa/status")
async def admin_mfa_status(authorization: str | None = Header(default=None)):
    claims = await admin_claims(authorization, require_aal2=False)
    state = await _supabase_user(authorization.split(" ", 1)[1].strip())
    factors = state.get("factors") or []
    verified = [f for f in factors if f.get("factor_type") == "totp" and f.get("status") == "verified"]
    return {"enabled": bool(verified), "aal": claims.get("aal", "aal1"), "factor_count": len(verified), "factor_ids": [str(f.get("id")) for f in verified]}


@app.post("/api/admin/auth/mfa/enroll")
async def admin_mfa_enroll(authorization: str | None = Header(default=None)):
    claims = await admin_claims(authorization, require_aal2=False)
    token = authorization.split(" ", 1)[1].strip()
    return await _supabase_request("/auth/v1/factors", payload={"factor_type": "totp", "friendly_name": "Atlas Trading Admin / Google Authenticator"}, access_token=token)


@app.post("/api/admin/auth/mfa/challenge")
async def admin_mfa_challenge(req: MfaChallengeRequest, authorization: str | None = Header(default=None)):
    await admin_claims(authorization, require_aal2=False)
    token = authorization.split(" ", 1)[1].strip()
    return await _supabase_request(f"/auth/v1/factors/{req.factor_id}/challenge", payload={}, access_token=token)


@app.post("/api/admin/auth/mfa/verify")
async def admin_mfa_verify(req: MfaVerifyRequest, authorization: str | None = Header(default=None)):
    await admin_claims(authorization, require_aal2=False)
    token = authorization.split(" ", 1)[1].strip()
    result = await _supabase_request(f"/auth/v1/factors/{req.factor_id}/verify", payload={"challenge_id": req.challenge_id, "code": req.code}, access_token=token)
    return result


@app.post("/api/admin/custody/tron/sweeps/prepare")
async def admin_prepare_tron_sweep(req: dict, authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    """Create a deterministic TRON USDT sweep intent for an external signer.

    This endpoint prepares accounting/audit state only. It never receives a private key,
    signs a transaction, or broadcasts a transaction. The signer boundary must be a
    dedicated custody/HSM/MPC service.
    """
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "TREASURY")
    try:
        wallet_id = int(req.get("wallet_id"))
        amount = req.get("amount_usdt")
        async with SessionLocal() as db:
            wallet = (await db.execute(select(Wallet).where(
                Wallet.id == wallet_id, Wallet.currency == "USDT", Wallet.network == "TRON",
                Wallet.status == "ACTIVE").with_for_update())).scalar_one_or_none()
            if not wallet or not wallet.deposit_address:
                raise HTTPException(404, "active TRON USDT wallet not found")
            balance = await customer_balance(db, wallet.customer_id, "USDT")
            if float(amount) < settings.usdt_tron_sweep_min_amount:
                raise HTTPException(400, "sweep amount is below configured minimum")
            # Sweeping only moves on-chain custody; it must not alter the customer liability ledger.
            intent = build_sweep_intent(wallet_id=wallet.id, source_address=wallet.deposit_address, amount_usdt=amount)
            existing = (await db.execute(select(TronSweep).where(TronSweep.idempotency_key == intent.idempotency_key))).scalar_one_or_none()
            if existing:
                return {"status": existing.status, "sweep_id": existing.id, "idempotency_key": existing.idempotency_key}
            sweep = TronSweep(wallet_id=wallet.id, source_address=wallet.deposit_address,
                              treasury_address=intent.treasury_address, amount_raw=intent.raw_amount,
                              currency="USDT", contract_address=intent.contract,
                              idempotency_key=intent.idempotency_key, status="READY_FOR_SIGNER",
                              detail_json=json.dumps({"customer_id": wallet.customer_id, "available_ledger": balance["available"],
                                                      "note": "custody movement only; customer liability unchanged"}, separators=(",", ":")))
            db.add(sweep)
            await db.commit()
            return {"status": sweep.status, "sweep_id": sweep.id, "intent": serialize_sweep_intent(intent)}
    except SweepError as exc:
        raise _safe_http_error(400, exc, "Unable to prepare the sweep request") from exc


@app.post("/api/admin/custody/tron/sweeps/{sweep_id}/record-broadcast")
async def admin_record_tron_sweep_broadcast(sweep_id: int, req: dict, authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    """Record a signer/broadcaster result without exposing signing material to Atlas."""
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "TREASURY")
    txid = str(req.get("transaction_id") or "").strip()
    if not txid:
        raise HTTPException(400, "transaction_id is required")
    async with SessionLocal() as db:
        sweep = (await db.execute(select(TronSweep).where(TronSweep.id == sweep_id).with_for_update())).scalar_one_or_none()
        if not sweep:
            raise HTTPException(404, "sweep not found")
        if sweep.transaction_id and sweep.transaction_id != txid:
            raise HTTPException(409, "sweep already has a different transaction id")
        sweep.transaction_id = txid
        sweep.status = "SUBMITTED"
        sweep.submitted_at = datetime.now(timezone.utc)
        await db.commit()
        return {"sweep_id": sweep.id, "status": sweep.status, "transaction_id": sweep.transaction_id}


@app.post("/api/admin/custody/tron/sweeps/{sweep_id}/reconcile")
async def admin_reconcile_tron_sweep(sweep_id: int, authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    """Reconcile a broadcast sweep against TRON solidified transaction + receipt evidence.

    A broadcast response is never treated as settlement. The signer remains outside Atlas.
    """
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "TREASURY")
    import httpx
    async with SessionLocal() as db:
        sweep = (await db.execute(select(TronSweep).where(TronSweep.id == sweep_id).with_for_update())).scalar_one_or_none()
        if not sweep:
            raise HTTPException(404, "sweep not found")
        if not sweep.transaction_id:
            raise HTTPException(409, "sweep has not been broadcast")
        txid = sweep.transaction_id
        try:
            headers = {"accept": "application/json"}
            if settings.usdt_trongrid_api_key:
                headers["TRON-PRO-API-KEY"] = settings.usdt_trongrid_api_key
            base = settings.usdt_trongrid_base_url.rstrip("/")
            async with httpx.AsyncClient(timeout=10.0) as client:
                body_r = await client.post(f"{base}/walletsolidity/gettransactionbyid", json={"value": txid}, headers=headers)
                receipt_r = await client.post(f"{base}/walletsolidity/gettransactioninfobyid", json={"value": txid}, headers=headers)
            tx_body = body_r.json() if body_r.status_code == 200 else {}
            receipt = receipt_r.json() if receipt_r.status_code == 200 else {}
            result, evidence = classify_solidified_sweep(
                tx_body=tx_body, receipt=receipt, transaction_id=txid,
                source=sweep.source_address, treasury=sweep.treasury_address,
                contract=sweep.contract_address, expected_raw_amount=sweep.amount_raw)
            sweep.detail_json = json.dumps({**(json.loads(sweep.detail_json or "{}") or {}), "reconciliation": evidence}, separators=(",", ":"))
            if result == "SETTLED":
                sweep.status = "SETTLED"
                sweep.confirmed_at = datetime.now(timezone.utc)
            elif result == "FAILED":
                sweep.status = "FAILED"
            elif result == "REVIEW":
                sweep.status = "REVIEW"
            await db.commit()
            return {"sweep_id": sweep.id, "status": sweep.status, "transaction_id": txid, "evidence": evidence}
        except httpx.HTTPError as exc:
            raise _safe_http_error(503, exc, "TRON reconciliation is temporarily unavailable") from exc


@app.get("/api/admin/custody/tron/sweeps")
async def admin_list_tron_sweeps(authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None), status: str | None = None):
    await auth(x_admin_token, authorization)
    async with SessionLocal() as db:
        stmt = select(TronSweep).order_by(desc(TronSweep.created_at)).limit(200)
        if status:
            stmt = stmt.where(TronSweep.status == status.upper())
        rows = (await db.execute(stmt)).scalars().all()
        return [{"id": r.id, "wallet_id": r.wallet_id, "amount_raw": r.amount_raw, "currency": r.currency,
                 "status": r.status, "transaction_id": r.transaction_id, "idempotency_key": r.idempotency_key,
                 "created_at": r.created_at.isoformat() if r.created_at else None,
                 "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                 "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None} for r in rows]


@app.get("/api/admin/custody/reconciliation")
async def admin_custody_reconciliation(authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    """Show customer-liability ledger and the configured TRON treasury balance.

    This endpoint is monitoring-only. It never credits a customer from the chain and never
    initiates a sweep. Customer credits originate only from confirmed, idempotent deposit events.
    """
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "READ_ONLY")
    import httpx
    async with SessionLocal() as db:
        rows = (await db.execute(select(CustomerLedgerAccount).where(CustomerLedgerAccount.currency == "USDT"))).scalars().all()
        liability_available = sum(float(r.available) for r in rows)
        liability_trading_reserved = sum(float(r.trading_reserved) for r in rows)
        liability_withdrawal_reserved = sum(float(r.withdrawal_reserved) for r in rows)
        customer_liabilities = liability_available + liability_trading_reserved + liability_withdrawal_reserved
        virtual_wallets = (await db.execute(select(Wallet).where(Wallet.currency == "USDT", Wallet.network == "TRON", Wallet.status == "ACTIVE"))).scalars().all()
    treasury_balance = None
    virtual_wallet_balances = {}
    chain_error = ""
    if settings.usdt_trongrid_api_key and settings.usdt_tron_treasury_address:
        try:
            headers = {"accept": "application/json", "TRON-PRO-API-KEY": settings.usdt_trongrid_api_key}
            base = settings.usdt_trongrid_base_url.rstrip("/")
            async with httpx.AsyncClient(timeout=10.0) as client:
                addresses = [settings.usdt_tron_treasury_address] + [w.deposit_address for w in virtual_wallets if w.deposit_address]
                for address in addresses:
                    response = await client.get(f"{base}/v1/accounts/{address}/trc20/balance",
                                                params={"contract_address": settings.usdt_tron_usdt_contract}, headers=headers)
                    response.raise_for_status()
                    data = response.json().get("data", [])
                    token = next((x for x in data if str((x.get("token_info") or {}).get("address") or "").lower() == settings.usdt_tron_usdt_contract.lower()), None)
                    balance = float(token.get("balance") or 0) / (10 ** int((token.get("token_info") or {}).get("decimals") or 6)) if token else 0.0
                    if address == settings.usdt_tron_treasury_address:
                        treasury_balance = balance
                    else:
                        virtual_wallet_balances[address] = balance
        except Exception as exc:
            chain_error = str(exc)
    custody_onchain = (treasury_balance or 0.0) + sum(virtual_wallet_balances.values()) if not chain_error else None
    coverage_gap = None if custody_onchain is None else custody_onchain - customer_liabilities
    return {
        "asset": "USDT", "network": "TRON", "treasury_address": settings.usdt_tron_treasury_address,
        "customer_liabilities": {"available": liability_available, "trading_reserved": liability_trading_reserved,
                                  "withdrawal_reserved": liability_withdrawal_reserved, "total": customer_liabilities},
        "active_virtual_deposit_addresses": len(virtual_wallets),
        "treasury_onchain_balance": treasury_balance,
        "virtual_wallet_onchain_balance": sum(virtual_wallet_balances.values()),
        "custody_onchain_balance": custody_onchain,
        "coverage_gap": coverage_gap,
        "status": "OK" if coverage_gap is not None and coverage_gap >= -1e-6 else "REVIEW",
        "chain_error": chain_error,
    }

@app.get("/api/admin/security/roles")
async def admin_list_roles(authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "ADMINISTRATOR")
    async with SessionLocal() as db:
        rows = (await db.execute(select(AdminRole).order_by(AdminRole.auth_user_id, AdminRole.role))).scalars().all()
        return [{"id": r.id, "auth_user_id": r.auth_user_id, "role": r.role, "active": r.active, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


@app.get("/api/admin/security/audit/verify")
async def admin_verify_audit_chain(authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None), limit: int = 5000):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "ADMINISTRATOR", "COMPLIANCE")
    import hashlib
    async with SessionLocal() as db:
        rows = (await db.execute(select(AuditLog).order_by(AuditLog.id.asc()).limit(max(1, min(20000, int(limit)))))).scalars().all()
    previous = ""
    checked = 0
    for row in rows:
        payload = json.dumps({"event": row.event, "detail": json_loads(row.detail), "actor_id": row.actor_id, "created_at": row.created_at.isoformat() if row.created_at else None, "previous_hash": previous}, sort_keys=True, separators=(",", ":"), default=str)
        expected = hashlib.sha256(payload.encode()).hexdigest()
        if row.previous_hash != previous or row.event_hash != expected:
            return {"ok": False, "checked": checked, "broken_at_id": row.id}
        previous = row.event_hash
        checked += 1
    return {"ok": True, "checked": checked, "head_hash": previous}


@app.post("/api/admin/security/roles")
async def admin_set_role(req: dict, authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "ADMINISTRATOR")
    uid = str(req.get("auth_user_id") or "").strip()
    role = str(req.get("role") or "").strip().upper()
    active = bool(req.get("active", True))
    if not uid or role not in ROLES:
        raise HTTPException(400, "auth_user_id and a valid role are required")
    row = await upsert_role(uid, role, active)
    await _audit("ADMIN_ROLE_CHANGED", {"target_user_id": uid, "role": role, "active": active})
    return {"id": row.id, "auth_user_id": row.auth_user_id, "role": row.role, "active": row.active}


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"settings": settings})


class CustomerCredentials(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    referral_code: str | None = Field(default=None, min_length=4, max_length=40)


class OtpSendRequest(BaseModel):
    email: str | None = None
    phone: str | None = None
    create_user: bool = False
    purpose: str = Field(default="login", pattern="^(login|withdrawal|destination_verification)$")
    destination: str | None = Field(default=None, min_length=30, max_length=50)
    amount: float | None = Field(default=None, gt=0)
    destination_tag: str | None = Field(default=None, max_length=120)
    network: str = Field(default="TRON", min_length=3, max_length=40)


class OtpVerifyRequest(BaseModel):
    email: str | None = None
    phone: str | None = None
    token: str = Field(min_length=6, max_length=8)
    purpose: str = Field(default="login", pattern="^(login|withdrawal|destination_verification)$")
    destination: str | None = Field(default=None, min_length=30, max_length=50)
    amount: float | None = Field(default=None, gt=0)
    destination_tag: str | None = Field(default=None, max_length=120)
    network: str = Field(default="TRON", min_length=3, max_length=40)
    otp_intent_token: str | None = Field(default=None, min_length=20, max_length=1200)


class FundingWebhook(BaseModel):
    customer_auth_user_id: str = Field(min_length=10, max_length=120)
    provider: str = Field(min_length=2, max_length=50)
    provider_reference: str = Field(min_length=2, max_length=180)
    amount: float = Field(gt=0)
    currency: str = Field(min_length=2, max_length=20)
    status: str = Field(default="CONFIRMED", pattern="^(PENDING|CONFIRMED|FAILED)$")
    metadata: dict = Field(default_factory=dict)


@app.post("/api/auth/signup")
async def customer_signup(req: CustomerCredentials):
    payload={"email": req.email, "password": req.password}
    result = await _supabase_request("/auth/v1/signup", payload=payload)
    # Referral attribution is completed when the authenticated customer profile is first created.
    if req.referral_code:
        result["referral_code"] = req.referral_code.strip().upper()
    return result


@app.post("/api/auth/login")
async def customer_login(req: CustomerCredentials):
    return await _supabase_request("/auth/v1/token?grant_type=password", payload={"email": req.email, "password": req.password})


@app.get("/api/auth/mfa/status")
async def customer_mfa_status(authorization: str | None = Header(default=None)):
    state = await _customer_mfa_state(authorization)
    return {"enabled": state["enabled"], "aal": state["aal"], "factor_count": state["factor_count"]}


@app.post("/api/auth/mfa/enroll")
async def customer_mfa_enroll(authorization: str | None = Header(default=None)):
    await customer_claims(authorization, require_aal2=False)
    token = authorization.split(" ", 1)[1].strip() if authorization else ""
    return await _supabase_request("/auth/v1/factors", payload={"factor_type": "totp", "friendly_name": "Atlas Trading / Google Authenticator"}, access_token=token)


class MfaChallengeRequest(BaseModel):
    factor_id: str = Field(min_length=10, max_length=80)


class MfaVerifyRequest(BaseModel):
    factor_id: str = Field(min_length=10, max_length=80)
    challenge_id: str = Field(min_length=10, max_length=80)
    code: str = Field(pattern=r"^\d{6}$")


@app.post("/api/auth/mfa/challenge")
async def customer_mfa_challenge(req: MfaChallengeRequest, authorization: str | None = Header(default=None)):
    await customer_claims(authorization, require_aal2=False)
    token = authorization.split(" ", 1)[1].strip() if authorization else ""
    state = await _customer_mfa_state(authorization)
    if req.factor_id not in state["factor_ids"]:
        raise HTTPException(403, "Invalid authenticator factor")
    return await _supabase_request(f"/auth/v1/factors/{req.factor_id}/challenge", payload={}, access_token=token)


@app.post("/api/auth/mfa/verify")
async def customer_mfa_verify(req: MfaVerifyRequest, authorization: str | None = Header(default=None)):
    await customer_claims(authorization, require_aal2=False)
    token = authorization.split(" ", 1)[1].strip() if authorization else ""
    state = await _customer_mfa_state(authorization)
    if req.factor_id not in state["factor_ids"]:
        raise HTTPException(403, "Invalid authenticator factor")
    return await _supabase_request(f"/auth/v1/factors/{req.factor_id}/verify", payload={"challenge_id": req.challenge_id, "code": req.code}, access_token=token)


def _otp_contact(user: dict, requested_email: str | None, requested_phone: str | None) -> tuple[str, str]:
    user_email = str(user.get("email") or "").strip().lower()
    user_phone = str(user.get("phone") or "").strip()
    supplied_email = str(requested_email or "").strip().lower()
    supplied_phone = str(requested_phone or "").strip()
    if supplied_email and supplied_phone:
        raise HTTPException(422, "Provide exactly one OTP contact")
    if supplied_email:
        if not user_email or not hmac.compare_digest(supplied_email, user_email):
            raise HTTPException(403, "OTP contact does not match the signed-in account")
        if not user.get("email_confirmed_at"):
            raise HTTPException(403, "The account email must be verified before withdrawal OTP can be used")
        return "email", user_email
    if supplied_phone:
        if not user_phone or not hmac.compare_digest(supplied_phone, user_phone):
            raise HTTPException(403, "OTP contact does not match the signed-in account")
        if not user.get("phone_confirmed_at"):
            raise HTTPException(403, "The account phone must be verified before withdrawal OTP can be used")
        return "sms", user_phone
    if user_email and user.get("email_confirmed_at"):
        return "email", user_email
    if user_phone and user.get("phone_confirmed_at"):
        return "sms", user_phone
    raise HTTPException(422, "No verified email or phone contact is available for this account")


def _otp_intent_token(uid: str, purpose: str, contact_hash: str, destination_fingerprint_value: str, proposal_digest_value: str) -> tuple[str, str, int]:
    token, jti, exp = _stepup_token(uid, purpose="otp_intent", destination_fingerprint=destination_fingerprint_value, proposal_digest_value=proposal_digest_value)
    # Contact identity is bound server-side in WithdrawalOtpIntent; the signed token carries only the jti and exact withdrawal digest.
    return token, jti, exp


@app.post("/api/auth/otp/send")
async def customer_otp_send(req: OtpSendRequest, authorization: str | None = Header(default=None)):
    purpose = req.purpose
    if purpose in {"withdrawal", "destination_verification"}:
        claims = await customer_claims(authorization)
        access_token = _bearer_token(authorization)
        user = await _supabase_user(access_token)
        user_id = str(claims.get("sub") or "")
        contact_type, contact = _otp_contact(user, req.email, req.phone)
        if req.network.upper() != "TRON":
            raise HTTPException(422, "Withdrawal verification currently supports TRON only")
        if not req.destination or not _tron_base58check_valid(req.destination.strip()):
            raise HTTPException(422, "A valid TRON destination is required")
        if purpose == "withdrawal" and req.amount is None:
            raise HTTPException(422, "Withdrawal OTP requires the withdrawal amount")
        profile_id: int
        async with SessionLocal() as db:
            profile = (await db.execute(select(CustomerProfile).where(CustomerProfile.auth_user_id == user_id))).scalar_one_or_none()
            if not profile:
                raise HTTPException(404, "Customer profile not found")
            fp = destination_fingerprint(req.destination.strip(), "USDT", req.network.upper())
            digest = proposal_digest(
                request_id="STEPUP", amount=req.amount or 0, currency="USDT",
                destination=req.destination.strip(), tag=req.destination_tag or "", network=req.network.upper(), provider=settings.payout_provider,
            )
            intent_token, jti, exp = _otp_intent_token(user_id, purpose, hashlib.sha256(contact.encode()).hexdigest(), fp, digest if purpose == "withdrawal" else "")
            db.add(WithdrawalOtpIntent(
                jti=jti, auth_user_id=user_id, purpose=purpose,
                contact_hash=hashlib.sha256(contact.encode()).hexdigest(),
                destination_fingerprint=fp if purpose in {"withdrawal", "destination_verification"} else "",
                proposal_digest=digest if purpose == "withdrawal" else "",
                expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
            ))
            await db.commit()
        contact_key = hashlib.sha256((purpose + ":" + contact).encode()).hexdigest()
        allowed_contact, _ = await allow_rate_limit(f"otp:contact:{contact_key}", max(1, settings.otp_rate_limit_per_minute))
        if not allowed_contact:
            raise HTTPException(429, "Verification code rate limit exceeded")
        try:
            result = await _supabase_request(
                "/auth/v1/otp",
                payload={contact_type: contact, "create_user": False},
            )
        except HTTPException:
            async with SessionLocal() as db:
                row = (await db.execute(select(WithdrawalOtpIntent).where(WithdrawalOtpIntent.jti == jti))).scalar_one_or_none()
                if row and not row.consumed_at:
                    row.consumed_at = datetime.now(timezone.utc)
                    await db.commit()
            raise
        return {"ok": True, "purpose": purpose, "otp_intent": intent_token, "expires_in": settings.withdrawal_step_up_minutes * 60, "contact_type": contact_type, "message": "Verification code sent."}

    if bool(req.email) == bool(req.phone):
        raise HTTPException(422, "Provide exactly one of email or phone")
    contact_type = "email" if req.email else "phone"
    contact = req.email.strip().lower() if req.email else req.phone.strip()
    result = await _supabase_request("/auth/v1/otp", payload={contact_type: contact, "create_user": bool(req.create_user)})
    return {"ok": True, "purpose": "login", "contact_type": contact_type, "message": "Verification code sent."}


@app.post("/api/auth/otp/verify")
async def customer_otp_verify(req: OtpVerifyRequest, authorization: str | None = Header(default=None)):
    if req.purpose == "login":
        if bool(req.email) == bool(req.phone):
            raise HTTPException(422, "Provide exactly one of email or phone")
        verify_type = "email" if req.email else "sms"
        contact = req.email.strip().lower() if req.email else req.phone.strip()
        result = await _supabase_request(
            "/auth/v1/verify",
            payload={"type": verify_type, verify_type if verify_type == "email" else "phone": contact, "token": req.token},
        )
        return result

    claims = await customer_claims(authorization)
    uid = str(claims.get("sub") or "")
    if not req.otp_intent_token:
        raise HTTPException(422, "OTP intent is required")
    access_token = _bearer_token(authorization)
    user = await _supabase_user(access_token)
    verify_type, contact = _otp_contact(user, req.email, req.phone)
    if req.network.upper() != "TRON" or not req.destination or not _tron_base58check_valid(req.destination.strip()):
        raise HTTPException(422, "A valid TRON destination is required")
    fp = destination_fingerprint(req.destination.strip(), "USDT", req.network.upper())
    expected_digest = proposal_digest(
        request_id="STEPUP", amount=req.amount or 0, currency="USDT",
        destination=req.destination.strip(), tag=req.destination_tag or "", network=req.network.upper(), provider=settings.payout_provider,
    ) if req.purpose == "withdrawal" else ""
    probe = _parse_stepup_token(req.otp_intent_token, uid, purpose="otp_intent", destination_fingerprint=fp, proposal_digest_value=expected_digest)
    if not probe:
        raise HTTPException(401, "OTP verification session has expired or is invalid")
    jti, _, _ = probe
    async with SessionLocal() as db:
        intent = (await db.execute(select(WithdrawalOtpIntent).where(WithdrawalOtpIntent.jti == jti, WithdrawalOtpIntent.auth_user_id == uid).with_for_update())).scalar_one_or_none()
        if not intent or intent.consumed_at or intent.expires_at < datetime.now(timezone.utc):
            raise HTTPException(401, "OTP verification session has expired or is invalid")
        if not hmac.compare_digest(intent.contact_hash, hashlib.sha256(contact.encode()).hexdigest()):
            raise HTTPException(403, "OTP contact does not match the issued verification")
        if not hmac.compare_digest(str(intent.destination_fingerprint), fp) or (intent.purpose == "withdrawal" and not hmac.compare_digest(str(intent.proposal_digest), expected_digest)):
            raise HTTPException(409, "Withdrawal details do not match the OTP verification request")
        # Verify the actual Supabase OTP before minting any local privilege.
        await _supabase_request(
            "/auth/v1/verify",
            payload={"type": verify_type, verify_type if verify_type == "email" else "phone": contact, "token": req.token},
        )
        intent.consumed_at = datetime.now(timezone.utc)
        if intent.purpose == "destination_verification":
            profile = (await db.execute(select(CustomerProfile).where(CustomerProfile.auth_user_id == uid))).scalar_one_or_none()
            if not profile:
                raise HTTPException(404, "Customer profile not found")
            await verify_destination(db, customer_id=profile.id, fingerprint=fp)
            await db.commit()
            await _audit("WITHDRAWAL_DESTINATION_VERIFIED", {"customer_id": profile.id, "fingerprint": fp})
            return {"ok": True, "purpose": "destination_verification", "destination_verified": True, "fingerprint": fp}
        token, token_jti, exp = _stepup_token(uid, "withdrawal", fp, expected_digest)
        db.add(WithdrawalStepUpToken(
            token_hash=hashlib.sha256(token.encode()).hexdigest(), jti=token_jti, auth_user_id=uid,
            purpose="withdrawal", destination_fingerprint=fp, proposal_digest=expected_digest,
            expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
        ))
        await db.commit()
    return {"ok": True, "purpose": "withdrawal", "step_up_token": token, "proposal_digest": expected_digest, "expires_in": settings.withdrawal_step_up_minutes * 60}


@app.post("/api/auth/password-reset")
async def customer_password_reset(req: dict):
    email = str(req.get("email") or "").strip()
    if not email:
        raise HTTPException(422, "Email is required")
    key = hashlib.sha256(email.lower().encode()).hexdigest()
    allowed, _ = await allow_rate_limit(f"password-reset:contact:{key}", max(1, settings.auth_rate_limit_per_minute))
    if not allowed:
        raise HTTPException(429, "Password reset rate limit exceeded")
    return await _supabase_request("/auth/v1/recover", payload={"email": email})


@app.post("/api/auth/logout")
async def customer_logout(authorization: str | None = Header(default=None)):
    # The Android client also clears its local bearer token. Server-side revocation is best-effort.
    if authorization:
        try:
            await _supabase_request("/auth/v1/logout", method="POST", access_token=authorization.split(" ", 1)[-1])
        except Exception:
            pass
    return {"ok": True}


@app.get("/api/plans")
async def public_plans():
    return [{"code":k, **v} for k,v in PLAN_DEFINITIONS.items()]


@app.get("/api/customer/billing")
async def customer_billing(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=False)
        sub = await _get_active_subscription(db, profile.id)
        plan = PLAN_DEFINITIONS.get(sub.plan_code if sub else "free", PLAN_DEFINITIONS["free"])
        code = (await db.execute(select(ReferralCode).where(ReferralCode.customer_id == profile.id))).scalar_one_or_none()
        referrals = (await db.execute(select(Referral).where(Referral.referrer_customer_id == profile.id))).scalars().all()
        commissions = (await db.execute(select(func.coalesce(func.sum(ReferralCommission.commission_amount), 0.0)).where(ReferralCommission.referral_customer_id == profile.id, ReferralCommission.status.in_(["PENDING","ELIGIBLE"])))).scalar_one()
        return {"plan": {"code": sub.plan_code if sub else "free", **plan}, "subscription": {"status": sub.status if sub else "active", "interval": sub.billing_interval if sub else "monthly", "period_end": sub.current_period_end.isoformat() if sub else None, "cancel_at_period_end": bool(sub.cancel_at_period_end) if sub else False}, "referral": {"code": code.code if code else None, "referred_count": len(referrals), "pending_commissions": float(commissions or 0)}}


@app.post("/api/customer/billing/checkout")
async def customer_billing_checkout(req: PlanChangeRequest, authorization: str | None = Header(default=None)):
    if req.plan == "free":
        raise HTTPException(409, "Free plan does not require checkout")
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=False)
        if not settings.stripe_enabled:
            return {"provider":"stripe", "configured":False, "plan":req.plan, "interval":req.interval, "amount":_plan_price(req.plan, req.interval), "message":"Stripe is not configured. Set Stripe price IDs and secret in Secret Manager before accepting payments."}
        referral = (await db.execute(select(Referral).where(Referral.referred_customer_id == profile.id))).scalar_one_or_none()
        session = await _stripe_checkout(req.plan, req.interval, profile.email, profile.id, referral_discount=bool(referral and settings.stripe_referral_coupon_id))
        return {"provider":"stripe", "configured":True, "checkout_url":session.get("url"), "session_id":session.get("id"), "plan":req.plan, "interval":req.interval}


@app.post("/api/customer/referral/code")
async def customer_referral_code(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=False)
        existing=(await db.execute(select(ReferralCode).where(ReferralCode.customer_id==profile.id))).scalar_one_or_none()
        if existing:
            return {"code":existing.code}
        code=f"ATLAS-{hashlib.sha256(f'{profile.auth_user_id}:{profile.id}'.encode()).hexdigest()[:10].upper()}"
        row=ReferralCode(customer_id=profile.id, code=code)
        db.add(row); await db.commit()
        return {"code":code}


@app.post("/api/customer/referral/claim")
async def customer_claim_referral(req: ReferralCodeRequest, authorization: str | None = Header(default=None)):
    code=(req.code or "").strip().upper()
    if not code: raise HTTPException(422,"Referral code is required")
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        existing=(await db.execute(select(Referral).where(Referral.referred_customer_id==profile.id))).scalar_one_or_none()
        if existing: return {"ok":True,"status":existing.status,"code":existing.referral_code}
        rc=(await db.execute(select(ReferralCode).where(ReferralCode.code==code,ReferralCode.active==True))).scalar_one_or_none()
        if not rc or rc.customer_id==profile.id: raise HTTPException(409,"Referral code is invalid")
        row=Referral(referral_code=code,referrer_customer_id=rc.customer_id,referred_customer_id=profile.id,status="PENDING")
        db.add(row); await db.commit(); return {"ok":True,"status":"PENDING","code":code}


@app.get("/api/customer/referrals")
async def customer_referrals(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=False)
        rows=(await db.execute(select(Referral).where(Referral.referrer_customer_id==profile.id).order_by(desc(Referral.created_at)))).scalars().all()
        comm=(await db.execute(select(ReferralCommission).where(ReferralCommission.referral_customer_id==profile.id).order_by(desc(ReferralCommission.created_at)).limit(100))).scalars().all()
        return {"referrals":[{"id":r.id,"code":r.referral_code,"status":r.status,"created_at":r.created_at.isoformat(),"qualified_at":r.qualified_at.isoformat() if r.qualified_at else None} for r in rows],"commissions":[{"amount":c.commission_amount,"status":c.status,"eligible_at":c.eligible_at.isoformat(),"paid_at":c.paid_at.isoformat() if c.paid_at else None} for c in comm]}


@app.post("/api/admin/billing/cost")
async def admin_billing_cost(req: CostEventRequest, authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    async with SessionLocal() as db:
        row=CostLedger(customer_id=req.customer_id,category=req.category,provider=req.provider,amount=req.amount,currency=req.currency.upper(),reference=req.reference)
        db.add(row); await db.commit()
        return {"ok":True,"id":row.id}


@app.post("/api/admin/billing/revenue")
async def admin_billing_revenue(req: RevenueEventRequest, authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    async with SessionLocal() as db:
        existing=(await db.execute(select(RevenueLedger).where(RevenueLedger.provider==req.provider,RevenueLedger.provider_reference==req.provider_reference))).scalar_one_or_none()
        if existing: return {"ok":True,"id":existing.id,"duplicate":True}
        row=RevenueLedger(customer_id=req.customer_id,subscription_id=req.subscription_id,provider=req.provider,provider_reference=req.provider_reference,gross_amount=req.gross_amount,refunds=req.refunds,net_amount=max(0,req.gross_amount-req.refunds),currency=req.currency.upper())
        db.add(row); await db.commit()
        return {"ok":True,"id":row.id}


@app.get("/api/admin/billing/margin")
async def admin_billing_margin(months: int = 1, authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    months=max(1,min(months,24)); cutoff=datetime.now(timezone.utc)-__import__('datetime').timedelta(days=31*months)
    async with SessionLocal() as db:
        revenue=float((await db.execute(select(func.coalesce(func.sum(RevenueLedger.net_amount),0.0)).where(RevenueLedger.created_at>=cutoff))).scalar_one() or 0)
        costs=float((await db.execute(select(func.coalesce(func.sum(CostLedger.amount),0.0)).where(CostLedger.created_at>=cutoff))).scalar_one() or 0)
        commissions=float((await db.execute(select(func.coalesce(func.sum(ReferralCommission.commission_amount),0.0)).where(ReferralCommission.created_at>=cutoff))).scalar_one() or 0)
        contribution=revenue-costs-commissions
        margin=(contribution/revenue*100) if revenue else 0.0
        active=int((await db.execute(select(func.count(Subscription.id)).where(Subscription.status.in_(["trialing","active","past_due"]),Subscription.plan_code!="free"))).scalar_one() or 0)
        return {"period_days":31*months,"gross_subscription_revenue":revenue,"operating_costs":costs,"referral_commissions":commissions,"contribution_profit":contribution,"contribution_margin_pct":margin,"active_paying_customers":active}


@app.post("/api/billing/stripe/webhook")
async def stripe_webhook(request: Request):
    raw = await request.body()
    if not settings.stripe_enabled or not settings.stripe_webhook_secret:
        raise HTTPException(503, "Stripe webhook is not configured")
    signature = request.headers.get("stripe-signature", "")
    import time as _time, hmac as _hmac
    parts = {}
    for item in signature.split(','):
        if '=' in item:
            k, v = item.split('=', 1)
            parts.setdefault(k, []).append(v)
    timestamp = (parts.get('t') or ['0'])[0]
    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(400, "Invalid webhook signature")
    if abs(int(_time.time()) - ts) > 300:
        raise HTTPException(400, "Expired webhook signature")
    signed = f"{timestamp}.{raw.decode('utf-8')}".encode()
    expected = _hmac.new(settings.stripe_webhook_secret.encode(), signed, hashlib.sha256).hexdigest()
    if not any(_hmac.compare_digest(expected, v) for v in parts.get('v1', [])):
        raise HTTPException(400, "Invalid webhook signature")
    payload = json.loads(raw.decode('utf-8'))
    event_id = str(payload.get('id') or '').strip()
    event_type = str(payload.get('type') or '')
    obj = ((payload.get('data') or {}).get('object') or {})
    if not event_id:
        raise HTTPException(400, "Stripe event id is required")
    metadata = obj.get('metadata') or {}
    event_created = payload.get('created')
    stripe_created_at = datetime.fromtimestamp(int(event_created), tz=timezone.utc) if event_created else None
    customer_id = int(metadata.get('atlas_customer_id') or obj.get('client_reference_id') or 0)

    async with SessionLocal() as db:
        try:
            async with db.begin_nested():
                existing_event = (await db.execute(select(StripeWebhookEvent).where(StripeWebhookEvent.event_id == event_id))).scalar_one_or_none()
                if existing_event:
                    return {"received": True, "duplicate": True}
                db.add(StripeWebhookEvent(event_id=event_id, event_type=event_type, stripe_created_at=stripe_created_at,
                                          payload_json=json.dumps(payload, separators=(",", ":")), status="RECEIVED"))
                await db.flush()
        except IntegrityError:
            return {"received": True, "duplicate": True}

        if event_type in ('checkout.session.completed', 'customer.subscription.created', 'customer.subscription.updated') and customer_id:
            plan = metadata.get('atlas_plan') or 'free'
            interval = metadata.get('atlas_interval') or 'monthly'
            sub_id = str(obj.get('subscription') or obj.get('id') or '')
            sub = None
            if sub_id:
                sub = (await db.execute(select(Subscription).where(Subscription.provider_subscription_id == sub_id).with_for_update())).scalar_one_or_none()
            if sub is None:
                sub = (await db.execute(select(Subscription).where(Subscription.customer_id == customer_id, Subscription.status.in_(["trialing", "active", "past_due"])).with_for_update())).scalars().first()
            if sub and stripe_created_at and sub.stripe_last_event_at and stripe_created_at < sub.stripe_last_event_at:
                ev = (await db.execute(select(StripeWebhookEvent).where(StripeWebhookEvent.event_id == event_id))).scalar_one()
                ev.status = 'STALE'
                await db.commit()
                return {"received": True, "stale": True}
            now = datetime.now(timezone.utc)
            if not sub:
                sub = Subscription(customer_id=customer_id, plan_code=plan, billing_interval=interval, status='active', provider='stripe',
                                   provider_customer_id=str(obj.get('customer') or ''), provider_subscription_id=sub_id,
                                   current_period_start=now, current_period_end=now, stripe_last_event_at=stripe_created_at)
            else:
                sub.plan_code = plan
                sub.billing_interval = interval
                sub.status = 'active'
                sub.provider = 'stripe'
                if sub_id and event_type != 'checkout.session.completed':
                    sub.provider_subscription_id = sub_id
                sub.provider_customer_id = str(obj.get('customer') or sub.provider_customer_id)
                if stripe_created_at:
                    sub.stripe_last_event_at = stripe_created_at
            db.add(sub)

        elif event_type == 'customer.subscription.deleted':
            sub_id = str(obj.get('id') or '')
            sub = (await db.execute(select(Subscription).where(Subscription.provider_subscription_id == sub_id).with_for_update())).scalar_one_or_none()
            if sub and stripe_created_at and sub.stripe_last_event_at and stripe_created_at < sub.stripe_last_event_at:
                ev = (await db.execute(select(StripeWebhookEvent).where(StripeWebhookEvent.event_id == event_id))).scalar_one()
                ev.status = 'STALE'
                await db.commit()
                return {"received": True, "stale": True}
            if sub:
                sub.status = 'canceled'
                sub.cancel_at_period_end = False
                sub.stripe_last_event_at = stripe_created_at or sub.stripe_last_event_at

        elif event_type == 'invoice.paid':
            amount = float(obj.get('amount_paid') or 0) / 100.0
            currency = str(obj.get('currency') or 'usd').upper()
            ref = str(obj.get('id') or '')
            if ref and not (await db.execute(select(RevenueLedger).where(RevenueLedger.provider == 'stripe', RevenueLedger.provider_reference == ref))).scalar_one_or_none():
                sub_id = str(obj.get('subscription') or '')
                sub = (await db.execute(select(Subscription).where(Subscription.provider_subscription_id == sub_id))).scalar_one_or_none()
                if sub:
                    db.add(RevenueLedger(customer_id=sub.customer_id, subscription_id=sub.id, provider='stripe', provider_reference=ref, gross_amount=amount, net_amount=amount, currency=currency))
                    referral = (await db.execute(select(Referral).where(Referral.referred_customer_id == sub.customer_id))).scalar_one_or_none()
                    if referral and amount > 0:
                        referral.status = 'QUALIFIED'
                        referral.qualified_at = referral.qualified_at or datetime.now(timezone.utc)
                        exists = (await db.execute(select(ReferralCommission).where(ReferralCommission.subscription_id == sub.id, ReferralCommission.referral_id == referral.id, ReferralCommission.provider_reference == ref))).scalar_one_or_none()
                        if not exists:
                            from datetime import timedelta
                            commission = quantize_money(amount * (settings.billing_referral_commission_pct / 100.0))
                            db.add(ReferralCommission(referral_id=referral.id, referral_customer_id=referral.referrer_customer_id,
                                referred_customer_id=sub.customer_id, subscription_id=sub.id, gross_revenue=amount,
                                commission_pct=settings.billing_referral_commission_pct, commission_amount=commission, status='ELIGIBLE',
                                provider_reference=ref, eligible_at=datetime.now(timezone.utc) + timedelta(days=settings.billing_referral_payout_delay_days)))
        ev = (await db.execute(select(StripeWebhookEvent).where(StripeWebhookEvent.event_id == event_id))).scalar_one()
        ev.status = 'PROCESSED'
        await db.commit()
    return {"received": True}


@app.get("/api/customer/me")
async def customer_me(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, claims = await get_customer(authorization, db)
        sub = await _get_active_subscription(db, profile.id)
        await db.commit()
        return {"id": profile.id, "auth_user_id": profile.auth_user_id, "email": profile.email,
                "display_name": profile.display_name, "status": profile.status, "plan": sub.plan_code if sub else "free", "subscription_status": sub.status if sub else "active"}


@app.get("/api/customer/wallets")
async def customer_wallets(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=True)
        rows = (await db.execute(select(Wallet).where(Wallet.customer_id == profile.id).order_by(Wallet.currency))).scalars().all()
        await db.commit()
        out = []
        for w in rows:
            bal = await customer_balance(db, profile.id, w.currency)
            out.append({"id": w.id, "currency": w.currency, "wallet_type": w.wallet_type,
                 "available_balance": bal["available"], "locked_balance": bal["trading_reserved"] + bal["withdrawal_reserved"],
                 "trading_reserved": bal["trading_reserved"], "withdrawal_reserved": bal["withdrawal_reserved"],
                 "status": w.status, "network": w.network, "deposit_address": w.deposit_address,
                 "token_contract": w.token_contract, "derivation_path": w.derivation_path, "created_at": w.created_at.isoformat()})
        return out


@app.get("/api/customer/usdt/deposit")
async def customer_usdt_deposit(authorization: str | None = Header(default=None)):
    if not settings.usdt_tron_enabled:
        raise HTTPException(503, "USDT TRON deposits are not enabled")
    if not settings.usdt_tron_account_xpub or not validate_tron_account_xpub(settings.usdt_tron_account_xpub):
        raise HTTPException(503, "USDT public wallet derivation is not configured correctly")
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db)
        # There is one wallet row per customer/currency. Reuse a pre-existing USDT
        # wallet created by a funding provider instead of querying only TRON and
        # attempting a second USDT row (which would violate uq_wallet_customer_currency).
        wallet = (await db.execute(select(Wallet).where(
            Wallet.customer_id == profile.id, Wallet.currency == "USDT"
        ).with_for_update())).scalar_one_or_none()
        if wallet and wallet.network not in ("", "TRON"):
            raise HTTPException(409, "The customer USDT wallet is assigned to a different network")
        if not wallet or not wallet.deposit_address or wallet.network != "TRON":
            address = derive_usdt_tron_address_from_xpub(settings.usdt_tron_account_xpub, profile.id)
            standard_path = f"m/44'/195'/0'/0/{profile.id}"
            if wallet:
                wallet.wallet_type = "TRADING"
                wallet.network = "TRON"
                wallet.deposit_address = address
                wallet.token_contract = settings.usdt_tron_usdt_contract
                wallet.derivation_path = standard_path
                wallet.status = "ACTIVE"
            else:
                wallet = Wallet(customer_id=profile.id, currency="USDT", wallet_type="TRADING",
                                network="TRON", deposit_address=address,
                                token_contract=settings.usdt_tron_usdt_contract,
                                derivation_path=standard_path, status="ACTIVE")
                db.add(wallet)
                await db.flush()
            await db.commit()
        elif not wallet.derivation_path:
            # Legacy wallet address is already the source of truth. The API deliberately
            # cannot reconstruct legacy private-key derivation because no master seed is
            # present in the runtime. Record the legacy path only through an offline
            # custody-recovery procedure. Deposits remain usable because the on-file
            # address itself is sufficient for scanning/crediting.
            wallet.derivation_path = "LEGACY_OFFLINE_RECOVERY_REQUIRED"
            await db.commit()
        balance = await customer_balance(db, profile.id, "USDT")
        if settings.usdt_tron_shared_deposit_mode:
            return {"currency": "USDT", "network": "TRON", "standard": "TRC-20",
                    "deposit_address": settings.usdt_tron_treasury_address,
                    "token_contract": settings.usdt_tron_usdt_contract,
                    "balance": balance["available"], "credit_mode": "MANUAL_REVIEW",
                    "warning": "Shared-address deposits cannot be auto-attributed safely on TRC-20. Do not rely on amount matching; submit the transaction hash for review."}
        return {"currency": "USDT", "network": "TRON", "standard": "TRC-20",
                "deposit_address": wallet.deposit_address,
                "token_contract": wallet.token_contract,
                "treasury_address": settings.usdt_tron_treasury_address,
                "balance": balance["available"],
                "credit_mode": "AUTOMATIC",
                "warning": "Send only USDT on TRON (TRC-20) to this customer-specific virtual deposit address. Funds are swept to the Atlas treasury wallet after confirmation."}


@app.get("/api/customer/ledger")
async def customer_ledger(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db)
        balance = await customer_balance(db, profile.id, "USDT")
        entries = await ledger_statement(db, profile.id, "USDT", 100)
        return {"currency": "USDT", "balance": balance, "entries": entries}


@app.get("/api/customer/funding")
async def customer_funding(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db)
        rows = (await db.execute(select(FundingTransaction).where(FundingTransaction.customer_id == profile.id)
                                 .order_by(desc(FundingTransaction.created_at)).limit(100))).scalars().all()
        await db.commit()
        return [{"id": f.id, "provider": f.provider, "provider_reference": f.provider_reference,
                 "amount": f.amount, "currency": f.currency, "status": f.status,
                 "created_at": f.created_at.isoformat(), "confirmed_at": f.confirmed_at.isoformat() if f.confirmed_at else None}
                for f in rows]


@app.post("/api/internal/funding/webhook")
async def funding_webhook(request: Request, x_funding_signature: str | None = Header(default=None)):
    raw = await request.body()
    if not _funding_signature_valid(raw, x_funding_signature):
        raise HTTPException(401, "Invalid funding webhook signature")
    payload = FundingWebhook.model_validate(json.loads(raw))
    async with SessionLocal() as db:
        customer = (await db.execute(select(CustomerProfile).where(CustomerProfile.auth_user_id == payload.customer_auth_user_id)
                                      .with_for_update())).scalar_one_or_none()
        if not customer:
            raise HTTPException(404, "Customer account not found")
        existing = (await db.execute(select(FundingTransaction).where(
            FundingTransaction.provider == payload.provider,
            FundingTransaction.provider_reference == payload.provider_reference))).scalar_one_or_none()
        if existing:
            incoming = payload.status
            current = str(existing.status or "PENDING").upper()
            if incoming == current:
                return {"ok": True, "id": existing.id, "status": existing.status, "wallet_id": existing.wallet_id, "idempotent": True}
            allowed = {"PENDING": {"CONFIRMED", "FAILED"}, "FAILED": {"CONFIRMED"}, "CONFIRMED": set()}
            if incoming not in allowed.get(current, set()):
                raise HTTPException(409, f"Invalid funding state transition: {current} -> {incoming}")
            currency = payload.currency.upper()
            wallet = (await db.execute(select(Wallet).where(Wallet.id == existing.wallet_id).with_for_update())).scalar_one_or_none()
            if not wallet:
                raise HTTPException(409, "Funding wallet no longer exists")
            existing.status = incoming
            existing.metadata_json = json.dumps(payload.metadata, separators=(",", ":"))
            if incoming == "CONFIRMED":
                wallet.status = "ACTIVE"
                existing.confirmed_at = existing.confirmed_at or datetime.now(timezone.utc)
                if currency == "USDT" and current != "CONFIRMED":
                    await post_deposit(db, customer_id=customer.id, wallet_id=wallet.id, amount=payload.amount,
                                        provider_reference=payload.provider_reference, metadata=payload.metadata)
                    await sync_wallet_from_ledger(db, customer.id, "USDT")
                    account = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == customer.id).with_for_update())).scalar_one_or_none()
                    if account:
                        bal = await customer_balance(db, customer.id, "USDT")
                        account.cash_equity = bal["available"] + bal["trading_reserved"]
                        account.equity = max(0.0, account.cash_equity + account.realized_pnl + account.unrealized_pnl)
                        account.peak_equity = max(account.peak_equity, account.equity)
            await db.commit()
            return {"ok": True, "id": existing.id, "status": existing.status, "wallet_id": existing.wallet_id, "idempotent": False, "state_transition": f"{current}->{incoming}"}
        currency = payload.currency.upper()
        wallet = (await db.execute(select(Wallet).where(Wallet.customer_id == customer.id, Wallet.currency == currency)
                                   .with_for_update())).scalar_one_or_none()
        if not wallet and payload.status == "CONFIRMED":
            wallet = Wallet(customer_id=customer.id, currency=currency, wallet_type="INTERNAL_TRADING", status="ACTIVE")
            db.add(wallet)
            await db.flush()
        if not wallet:
            # Pending funding does not create a spendable wallet yet.
            wallet = Wallet(customer_id=customer.id, currency=currency, wallet_type="INTERNAL_TRADING", status="PENDING")
            db.add(wallet)
            await db.flush()
        funding = FundingTransaction(customer_id=customer.id, wallet_id=wallet.id,
            provider=payload.provider, provider_reference=payload.provider_reference,
            amount=payload.amount, currency=currency, status=payload.status,
            metadata_json=json.dumps(payload.metadata, separators=(",", ":")))
        if payload.status == "CONFIRMED":
            wallet.status = "ACTIVE"
            funding.confirmed_at = datetime.now(timezone.utc)
            if currency == "USDT":
                await post_deposit(db, customer_id=customer.id, wallet_id=wallet.id, amount=payload.amount,
                                    provider_reference=payload.provider_reference, metadata=payload.metadata)
                await sync_wallet_from_ledger(db, customer.id, "USDT")
                account = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == customer.id).with_for_update())).scalar_one_or_none()
                if account:
                    bal = await customer_balance(db, customer.id, "USDT")
                    account.cash_equity = bal["available"] + bal["trading_reserved"]
                    account.equity = max(0.0, account.cash_equity + account.realized_pnl + account.unrealized_pnl)
                    account.peak_equity = max(account.peak_equity, account.equity)
        db.add(funding)
        await db.commit()
        return {"ok": True, "id": funding.id, "status": funding.status,
                "wallet_id": wallet.id, "wallet_created": True}



@app.post("/api/admin/binance/customer-subaccount/plan")
async def admin_binance_customer_subaccount_plan(req: BinanceSubAccountProvisionRequest, authorization: str | None = Header(default=None)):
    """Create a least-privilege Binance Broker provisioning plan.

    This endpoint does not create Binance credentials. Actual provisioning is
    an explicit operator step because Binance applies account/KYC eligibility.
    The returned plan deliberately excludes universal-transfer permission.
    """
    if not settings.binance_customer_subaccounts_enabled:
        raise HTTPException(403, "Binance customer subaccounts are disabled")
    # All production admin APIs must use the centralized Supabase + AAL2 gate.
    claims = await auth(None, authorization)
    await require_role(claims, "OPERATIONS")
    try:
        return build_provision_plan(req.customer_id, req.tag)
    except BinanceSubAccountError as exc:
        raise _safe_http_error(400, exc, "Unable to prepare the Binance subaccount request") from exc


class CustomerOandaConnectRequest(BaseModel):
    account_id: str = Field(min_length=3, max_length=80)
    api_token: str = Field(min_length=20, max_length=512)
    practice: bool = True


@app.post("/api/customer/broker/oanda/connect")
async def customer_connect_oanda(req: CustomerOandaConnectRequest, authorization: str | None = Header(default=None)):
    if not req.practice:
        raise HTTPException(403, "AtlasRisk supports OANDA practice/demo only; live OANDA accounts are not supported")
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=True)
        from .forex_oanda import OandaBroker, OandaConfig, OandaError
        broker = OandaBroker(OandaConfig(req.account_id.strip(), req.api_token.strip(), True, settings.oanda_timeout_seconds))
        try:
            summary = (await asyncio.to_thread(broker.account)).get("account") or {}
            if str(summary.get("id") or "") != req.account_id.strip():
                raise HTTPException(400, "OANDA account identity does not match the supplied account ID")
        except OandaError as exc:
            raise _safe_http_error(400, exc, "OANDA verification failed") from exc
        finally:
            broker.close()
        row = (await db.execute(select(CustomerOandaAccount).where(CustomerOandaAccount.customer_id == profile.id).with_for_update())).scalar_one_or_none()
        if row is None:
            row = CustomerOandaAccount(customer_id=profile.id, account_id=req.account_id.strip(), api_token=req.api_token.strip(), practice=True, can_trade=True, scope_status="OANDA_PROVIDER_TOKEN_ACCESS_CONFIRMED", status="VERIFIED", last_verified_at=datetime.now(timezone.utc))
            db.add(row)
        else:
            row.account_id=req.account_id.strip(); row.api_token=req.api_token.strip(); row.practice=True; row.can_trade=True; row.scope_status="OANDA_PROVIDER_TOKEN_ACCESS_CONFIRMED"; row.status="VERIFIED"; row.last_verified_at=datetime.now(timezone.utc)
        await db.commit()
        return {"ok": True, "status": "VERIFIED", "practice": True, "environment": "practice", "execution_authority": "demo-only", "account_id": row.account_id}


@app.get("/api/customer/bot")
async def customer_bot_status(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=False)
        rows = (await db.execute(select(AdaptiveTradingBot).where(AdaptiveTradingBot.customer_id == profile.id).order_by(desc(AdaptiveTradingBot.updated_at)).limit(20))).scalars().all()
        return [{"id": r.id, "name": r.name, "asset": r.asset, "symbol": r.symbol, "exchange": r.exchange, "timeframe": r.timeframe, "status": r.status, "mode": r.mode, "interval_seconds": r.interval_seconds, "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None, "next_run_at": r.next_run_at.isoformat() if r.next_run_at else None, "last_decision": r.last_decision, "last_stage": r.last_stage, "last_model_version": r.last_model_version, "last_error": r.last_error} for r in rows]


@app.post("/api/customer/bot/{bot_id}/action")
async def customer_bot_action(bot_id: int, req: BotActionRequest, authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=True)
        await _require_feature(db, profile.id, "automated_entry_exit")
        row = (await db.execute(select(AdaptiveTradingBot).where(AdaptiveTradingBot.id == bot_id, AdaptiveTradingBot.customer_id == profile.id).with_for_update())).scalar_one_or_none()
        if not row:
            raise HTTPException(404, "Adaptive AI bot not found")
        if req.action == "START":
            if str(row.mode).upper() == "LIVE":
                try:
                    await assert_live_system_enabled(
                        db, asset=row.asset, customer_id=profile.id, exchange=row.exchange,
                        side="buy", quantity=1.0, reduce_only=False,
                    )
                except LiveExecutionBlocked as exc:
                    raise _safe_http_error(403, exc, "Live bot cannot be started") from exc
            row.status = "RUNNING"
            row.next_run_at = datetime.now(timezone.utc)
        else:
            row.status = "STOPPED"
            row.next_run_at = None
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        return {"id": row.id, "status": row.status, "mode": row.mode, "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None}


@app.get("/api/customer/bot/model-status")
async def customer_bot_model_status(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=False)
    # Model artifacts are market-specific, not customer-specific; this endpoint reports
    # only the requested default market's model state and never exposes model file paths.
    req = MarketRequest()
    policy = AdaptiveModelPolicy(
        max_age_hours=settings.adaptive_retrain_hours,
        min_sharpe=settings.adaptive_min_sharpe,
        max_drawdown=settings.adaptive_max_drawdown,
        min_trades=settings.adaptive_min_trades,
        min_total_return=settings.adaptive_min_total_return,
    )
    status = adaptive_model_status(model_file(req), policy)
    status.pop("model_path", None)
    status["customer_id"] = profile.id
    return status


@app.post("/api/customer/bot/start")
async def customer_start_bot(req: CustomerBotStartRequest, authorization: str | None = Header(default=None)):
    """Analyze, validate, obtain two independent AI safety approvals, then execute a customer-scoped plan."""
    _assert_established_noncrypto(req)
    if req.asset in {"forex", "commodity"}:
        req.symbol = _normalize_oanda_instrument(req.symbol)
        req.exchange = "oanda"
    if not settings.strategy_engine_enabled:
        raise HTTPException(403, "Strategy engine is disabled")
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=True)
        plan, subscription = await _subscription_entitlements(db, profile.id)
        if req.asset == "crypto" and settings.adaptive_require_established_crypto:
            established = {x.strip().upper() for x in settings.adaptive_established_symbols.split(",") if x.strip()}
            if req.symbol.upper() not in established:
                raise HTTPException(422, "Adaptive AI trading is limited to Atlas established/liquid crypto markets")
        if not plan.get("live") and not settings.paper_trading:
            raise HTTPException(403, "Your Atlas plan does not include live automation")
        state = await db.get(AppState, 1)
        if not state or state.kill_switch:
            raise HTTPException(409, "Trading is halted by the platform risk state")
        candidate = None
        if req.strategy_candidate_id is not None:
            candidate = (await db.execute(select(StrategyCandidate).where(StrategyCandidate.id == req.strategy_candidate_id, StrategyCandidate.customer_id == profile.id))).scalar_one_or_none()
            if candidate is None or candidate.status != "VALIDATED" or not candidate.live_approved:
                raise HTTPException(409, "Strategy candidate must pass validation and explicit live approval before autonomous deployment")
            if candidate.asset != req.asset or candidate.symbol != req.symbol or candidate.exchange != req.exchange or candidate.timeframe != req.timeframe:
                raise HTTPException(409, "Strategy candidate does not match the selected market configuration")
        account = await _get_or_create_customer_trading_account(db, profile)
        paper_mode = bool(
            settings.paper_trading
            or not settings.live_trading_enabled
            or not state.live_enabled
            or req.asset in {"forex", "commodity"}
        )
        if not paper_mode:
            try:
                await assert_live_system_enabled(
                    db, asset=req.asset, customer_id=profile.id, exchange=req.exchange,
                    side="buy", quantity=1.0, reduce_only=False,
                )
            except LiveExecutionBlocked as exc:
                raise _safe_http_error(403, exc, "Live bot cannot be armed") from exc
        equity = max(0.0, float(account.equity))
        account_id = account.id
        bot_id = None
        if req.autonomous:
            existing_bot = (await db.execute(select(AdaptiveTradingBot).where(AdaptiveTradingBot.customer_id == profile.id, AdaptiveTradingBot.name == "Atlas Adaptive AI").with_for_update())).scalar_one_or_none()
            if not existing_bot:
                existing_bot = AdaptiveTradingBot(customer_id=profile.id, trading_account_id=account.id, name="Atlas Adaptive AI", asset=req.asset, symbol=req.symbol, exchange=req.exchange, timeframe=req.timeframe, days=req.days, risk_fraction=req.risk_fraction or settings.risk_per_trade, interval_seconds=req.interval_seconds, strategy_candidate_id=req.strategy_candidate_id, status="RUNNING", mode="LIVE" if not paper_mode else "PAPER")
                db.add(existing_bot)
                await db.flush()
            else:
                existing_bot.trading_account_id = account.id
                existing_bot.asset = req.asset
                existing_bot.symbol = req.symbol
                existing_bot.exchange = req.exchange
                existing_bot.timeframe = req.timeframe
                existing_bot.days = req.days
                existing_bot.risk_fraction = req.risk_fraction or settings.risk_per_trade
                existing_bot.interval_seconds = req.interval_seconds
                existing_bot.strategy_candidate_id = req.strategy_candidate_id
                existing_bot.status = "RUNNING"
                existing_bot.mode = "LIVE" if not paper_mode else "PAPER"
                existing_bot.consecutive_errors = 0
                existing_bot.last_error = ""
                existing_bot.next_run_at = datetime.now(timezone.utc)
            bot_id = existing_bot.id
        await db.commit()

    try:
        df = await _fetch_customer_oanda_data(profile.id, req) if req.asset in {"forex", "commodity"} else await asyncio.to_thread(market_data, req)
        data_safe, data_reasons = _market_data_quality(df, req.timeframe, req.asset)
        spread_bps = await _customer_oanda_spread_bps(profile.id, req.symbol) if req.asset in {"forex", "commodity"} else await asyncio.to_thread(_current_spread_bps, req)
        if spread_bps is None and not paper_mode:
            data_safe = False
            data_reasons.append("live_spread_unavailable")
        derivatives_context = {"status": "DISABLED"}
        if req.asset == "crypto" and settings.derivatives_risk_enabled:
            try:
                derivatives_context = await fetch_public_derivatives_context(req.exchange, req.symbol)
            except Exception as exc:  # noqa: BLE001
                derivatives_context = {"status": "ERROR", "reason": str(exc)}
            if not paper_mode and settings.derivatives_risk_fail_closed_live and derivatives_context.get("status") in {"ERROR", "UNAVAILABLE", "UNSUPPORTED_EXCHANGE", "SYMBOL_UNAVAILABLE"}:
                data_safe = False
                data_reasons.append("derivatives_context_unavailable")
        cfg = EntryExitConfig()
        base_deterministic = await asyncio.to_thread(start_bot_decision, df, cfg, ai_safe=True, data_safe=data_safe, spread_bps=spread_bps)
        base_deterministic["data_quality"] = {"safe": data_safe, "reasons": data_reasons, "spread_bps": spread_bps, "derivatives_context": derivatives_context}

        # Regime-aware strategy router sits between market-data validation and the
        # existing ML/risk gates. It may replace the fixed entry/exit strategy, but
        # it never bypasses risk, protective-stop or exchange controls.
        router = {"status": "DISABLED"}
        router_cfg = StrategyConfig(
            signal_threshold=settings.strategy_signal_threshold,
            target_vol_annual=settings.strategy_target_vol_annual,
            max_leverage=settings.strategy_max_leverage,
            stop_atr=settings.strategy_stop_atr,
            take_profit_atr=settings.strategy_take_profit_atr,
        )
        deterministic = dict(base_deterministic)
        if settings.adaptive_strategy_router_enabled and req.strategy_candidate_id is None and data_safe and (spread_bps is None or spread_bps <= cfg.max_spread_bps):
            async with SessionLocal() as state_db:
                bot_row = await state_db.get(AdaptiveTradingBot, bot_id) if bot_id else None
                outcomes = []
                if profile.id:
                    outcomes = list((await state_db.execute(
                        select(StrategyOutcome).where(StrategyOutcome.customer_id == profile.id, StrategyOutcome.asset == req.asset, StrategyOutcome.symbol == req.symbol)
                        .order_by(desc(StrategyOutcome.created_at)).limit(200)
                    )).scalars().all())
                current_strategy = bot_row.active_strategy if bot_row else None
                last_switched = bot_row.strategy_last_switched_at if bot_row else None
                cooldown_active = bool(last_switched and (datetime.now(timezone.utc) - last_switched).total_seconds() < settings.adaptive_strategy_switch_cooldown_minutes * 60)
                current_regime = str(classify_regime(df, asset=req.asset).iloc[-1]) if len(df) else None
                online_scores = online_strategy_scores(outcomes, current_regime=current_regime, timeframe=req.timeframe, half_life_days=settings.adaptive_strategy_online_half_life_days, min_observations=settings.adaptive_strategy_online_min_observations)
                router = await asyncio.to_thread(
                    select_strategy, df, router_cfg, asset=req.asset, current_strategy=current_strategy,
                    cooldown_active=cooldown_active, min_regime_bars=settings.adaptive_strategy_min_regime_bars,
                    switch_min_advantage=settings.adaptive_strategy_switch_min_advantage,
                    min_trades=settings.adaptive_strategy_min_trades, costs_bps=settings.adaptive_strategy_cost_bps,
                    online_scores=online_scores, online_weight=settings.adaptive_strategy_online_weight,
                    blend_enabled=settings.adaptive_strategy_blend_enabled, blend_top_n=settings.adaptive_strategy_blend_top_n,
                )
                # Validate the router as a whole, not just the component strategies.
                # Cache the expensive walk-forward evidence on the bot and refresh it with
                # the same cadence as model research.
                router_json = json.loads(bot_row.strategy_selection_json or "{}") if bot_row and bot_row.strategy_selection_json else {}
                validated_at = router_json.get("validated_at")
                refresh_router = True
                if validated_at:
                    try:
                        dt = datetime.fromisoformat(str(validated_at).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        refresh_router = (datetime.now(timezone.utc) - dt).total_seconds() > settings.adaptive_retrain_hours * 3600
                    except Exception:
                        refresh_router = True
                if refresh_router and len(df) >= settings.adaptive_strategy_router_min_train + 250:
                    router_validation = await asyncio.to_thread(
                        policy_walk_forward_backtest, df, router_cfg, asset=req.asset,
                        costs_bps=settings.adaptive_strategy_cost_bps, folds=settings.adaptive_strategy_router_folds,
                        min_train=settings.adaptive_strategy_router_min_train, min_trades=settings.adaptive_strategy_min_trades,
                        switch_min_advantage=settings.adaptive_strategy_switch_min_advantage,
                        min_regime_bars=settings.adaptive_strategy_min_regime_bars,
                        decision_stride=settings.adaptive_strategy_policy_validation_stride_bars,
                    )
                    router_json = {"validated_at": datetime.now(timezone.utc).isoformat(), "validation": router_validation}
                else:
                    router_validation = router_json.get("validation") or {"status": "NOT_YET_VALIDATED"}
                fold_returns = [float(x.get("total_return", 0.0)) for x in (router_validation.get("folds") or [])]
                positive_ratio = (sum(x > 0 for x in fold_returns) / len(fold_returns)) if fold_returns else 0.0
                router_validation_gate = {
                    "passed": bool(router_validation.get("status") == "OK" and len(fold_returns) >= settings.adaptive_strategy_router_folds
                                   and float(router_validation.get("total_return", -1.0)) >= 0.0
                                   and positive_ratio >= settings.adaptive_strategy_router_required_positive_fold_ratio
                                   and (min(fold_returns) if fold_returns else -1.0) >= -0.20),
                    "positive_fold_ratio": positive_ratio,
                    "folds": len(fold_returns),
                    "required_positive_fold_ratio": settings.adaptive_strategy_router_required_positive_fold_ratio,
                }
                router["validation"] = router_validation
                router["validation_gate"] = router_validation_gate
                if not router_validation_gate["passed"] and not paper_mode:
                    router = {"status": "VALIDATION_FAILED", "reason": "strategy_router_oos_gate_failed",
                              "validation": router_validation, "validation_gate": router_validation_gate}

        if router.get("status") == "OK" and router.get("strategy") not in {"none", ""}:
            execution_strategy = "ensemble" if len(router.get("blend") or []) > 1 else str(router["strategy"])
            router_plan = await asyncio.to_thread(
                strategy_trade_plan, df, execution_strategy, signal=float(router.get("signal", 0.0)),
                atr_multiplier_stop=cfg.stop_atr, reward_r=cfg.target_r, min_reward_risk=cfg.min_reward_risk,
                cfg=router_cfg, asset=req.asset,
            )
            if router_plan is not None:
                plan = router_plan
                deterministic = {
                    "decision": "TRADE", "safe": True, "timestamp": df.index[-1].isoformat(), "reasons": [],
                    "trade_plan": plan, "rules": asdict(cfg), "strategy_router": router,
                    "data_quality": base_deterministic["data_quality"],
                    "ai_role": "safety/context veto only; strategy router selects the validated family",
                }
            else:
                deterministic = dict(base_deterministic)
        if bot_id and router.get("status") == "OK":
            async with SessionLocal() as strategy_state_db:
                strategy_row = await strategy_state_db.get(AdaptiveTradingBot, bot_id, with_for_update=True)
                if strategy_row:
                    selected_strategy = str(router.get("strategy") or "")
                    previous_strategy = str(strategy_row.active_strategy or "")
                    if selected_strategy and selected_strategy != previous_strategy:
                        strategy_row.strategy_switch_count = int(strategy_row.strategy_switch_count or 0) + 1
                        strategy_row.strategy_last_switched_at = datetime.now(timezone.utc)
                    strategy_row.active_strategy = selected_strategy
                    strategy_row.active_regime = str(router.get("regime") or "")
                    strategy_row.strategy_selection_json = json.dumps(router, default=str)[:200000]
                    await strategy_state_db.commit()

        if deterministic["decision"] != "TRADE":
            await _audit("CUSTOMER_BOT_NO_TRADE", {"customer_id": profile.id, "symbol": req.symbol, "reasons": deterministic["reasons"], "strategy_router": router})
            return {"decision": "NO_TRADE", "stage": "strategy_router_or_deterministic_gate", "analysis": deterministic, "strategy_router": router, "execution": None}

        plan = deterministic["trade_plan"]
        adaptive = None
        if settings.adaptive_ai_enabled:
            adaptive_policy = AdaptiveModelPolicy(
                max_age_hours=settings.adaptive_retrain_hours,
                min_sharpe=settings.adaptive_min_sharpe,
                max_drawdown=settings.adaptive_max_drawdown,
                min_trades=settings.adaptive_min_trades,
                min_total_return=settings.adaptive_min_total_return,
            )
            adaptive = await asyncio.to_thread(
                ensure_adaptive_model, df, model_file(req),
                asset=req.asset, min_train=req.min_train if hasattr(req, "min_train") else settings.research_min_train,
                folds=req.folds if hasattr(req, "folds") else settings.research_folds,
                threshold=settings.research_ai_threshold, policy=adaptive_policy,
            )
            await _record_model_experiment(model_file(req), req.asset, adaptive)
            if adaptive.get("status") == "CHALLENGER_REJECTED" and adaptive.get("promotion") == "NO_MODEL":
                return {
                    "decision": "NO_TRADE", "stage": "adaptive_model_gate",
                    "analysis": deterministic, "adaptive_model": adaptive, "execution": None,
                }
            if adaptive.get("status") == "CHALLENGER_REJECTED" and adaptive.get("promotion") == "RETAIN_CHAMPION":
                # A stale champion is safer than an unvalidated challenger, but it must
                # be treated as research-only once it exceeds the configured freshness window.
                if not adaptive_model_status(model_file(req), adaptive_policy).get("fresh", False):
                    return {
                        "decision": "NO_TRADE", "stage": "adaptive_model_stale",
                        "analysis": deterministic, "adaptive_model": adaptive, "execution": None,
                    }
            try:
                ml_signal = await asyncio.to_thread(predict_latest, df, model_file(req), settings.research_ai_threshold)
            except Exception as exc:
                return {
                    "decision": "NO_TRADE", "stage": "adaptive_model_prediction",
                    "analysis": deterministic, "adaptive_model": adaptive,
                    "ml_error": str(exc), "execution": None,
                }
            deterministic_side = str(plan["side"]) if deterministic.get("trade_plan") else "flat"
            ml_side = "buy" if ml_signal["signal"] > 0 else ("sell" if ml_signal["signal"] < 0 else "flat")
            # The learned model is an independent confirmation layer: disagreement or
            # flat prediction vetoes the deterministic setup instead of overriding risk.
            if deterministic_side != ml_side:
                await _audit("CUSTOMER_BOT_ML_VETO", {"customer_id": profile.id, "symbol": req.symbol, "deterministic_side": deterministic_side, "ml_side": ml_side, "model_version": ml_signal.get("model_version")})
                return {
                    "decision": "NO_TRADE", "stage": "adaptive_model_confirmation",
                    "analysis": deterministic, "adaptive_model": adaptive,
                    "ml_signal": ml_signal, "execution": None,
                }

        packet = {
            "symbol": req.symbol, "asset": req.asset, "exchange": req.exchange, "timeframe": req.timeframe,
            "market_timestamp": deterministic["timestamp"], "trade_plan": plan,
            "deterministic_rules": deterministic["rules"],
            "strategy_router": router,
            "price_context": {"latest_close": float(df.close.iloc[-1]), "bars": int(len(df)), "spread_bps": spread_bps},
            "data_quality": deterministic["data_quality"],
            "adaptive_model": adaptive or {"status": "DISABLED"},
            "strategy_router": router,
            "ml_signal": ml_signal if settings.adaptive_ai_enabled else {"status": "DISABLED"},
        }
        ai_review = await dual_ai_trade_safety_review(packet)
        if not ai_review["safe"]:
            stage = "ai_safety_not_configured" if not ai_review.get("configured", True) else "ai_safety_gate"
            await _audit("CUSTOMER_BOT_AI_NOT_CONFIGURED" if stage == "ai_safety_not_configured" else "CUSTOMER_BOT_AI_VETO",
                         {"customer_id": profile.id, "symbol": req.symbol, "ai_review": ai_review})
            return {"decision": "NO_TRADE", "stage": stage, "analysis": deterministic, "ai_review": ai_review, "execution": None}

        risk_fraction = req.risk_fraction if req.risk_fraction is not None else settings.risk_per_trade
        risk_cash = equity * risk_fraction
        distance = abs(float(plan["entry_price"]) - float(plan["stop_loss_price"]))
        if distance <= 0:
            raise HTTPException(409, "Invalid risk distance")
        quantity = risk_cash / distance
        quantity = min(quantity, settings.max_notional_usd / max(float(plan["entry_price"]), 1e-12))
        if quantity <= 0:
            raise HTTPException(409, "Calculated quantity is zero")

        signal = {
            "score": float(deterministic.get("trade_plan", {}).get("reward_risk", 0.0)),
            "side": plan["side"],
            "deterministic_gate": deterministic,
            "strategy_router": router,
            "ai_safety_review": ai_review,
            "customer_id": profile.id,
            "trading_account_id": account_id,
            "bot_id": bot_id,
            "regime": str(router.get("regime") or "UNKNOWN"),
            "strategy": str(router.get("strategy") or plan.get("strategy") or "ensemble"),
            "model_version": str((adaptive or {}).get("model_version") or ""),
        }
        execution = await execute_signal(
            req.symbol, plan["side"], quantity, float(plan["entry_price"]), signal,
            req.exchange, req.timeframe, deterministic["timestamp"],
            force_paper=paper_mode, stop_loss_price=float(plan["stop_loss_price"]),
            take_profit_price=float(plan["take_profit_price"]), strategy=str(router.get("strategy") or plan.get("strategy") or "atlas-gated-entry-exit-v2"), asset=req.asset,
            customer_id=profile.id,
        )
        await _audit("CUSTOMER_BOT_TRADE", {
            "customer_id": profile.id, "trading_account_id": account_id, "symbol": req.symbol, "decision": "TRADE",
            "mode": execution.get("mode"), "trade_id": execution.get("trade_id"),
            "side": plan["side"], "entry": plan["entry_price"], "stop": plan["stop_loss_price"],
            "target": plan["take_profit_price"], "quantity": quantity,
        })
        if bot_id:
            async with SessionLocal() as state_db:
                row = await state_db.get(AdaptiveTradingBot, bot_id)
                if row and row.status == "RUNNING":
                    now2 = datetime.now(timezone.utc)
                    row.last_run_at = now2
                    row.next_run_at = now2 + __import__("datetime").timedelta(seconds=max(60, row.interval_seconds))
                    row.last_decision = "TRADE"
                    row.last_stage = "execution"
                    row.last_model_version = str((adaptive or {}).get("model_version", ""))
                    selected_strategy = str(router.get("strategy") or plan.get("strategy") or "")
                    previous_strategy = str(row.active_strategy or "")
                    if selected_strategy and selected_strategy != previous_strategy:
                        row.strategy_switch_count = int(row.strategy_switch_count or 0) + 1
                        row.strategy_last_switched_at = now2
                    row.active_strategy = selected_strategy
                    row.active_regime = str(router.get("regime") or "")
                    row.strategy_selection_json = json.dumps(router, default=str)[:200000]
                    row.last_error = ""
                    row.consecutive_errors = 0
                    await state_db.commit()
        return {
            "decision": "TRADE", "mode": execution.get("mode"), "analysis": deterministic,
            "adaptive_model": adaptive or {"status": "DISABLED"},
            "ml_signal": ml_signal if settings.adaptive_ai_enabled else {"status": "DISABLED"},
            "ai_review": ai_review, "trade_plan": {**plan, "quantity": quantity, "risk_cash": risk_cash},
            "execution": execution,
            "autonomous_bot_id": bot_id,
            "autonomous_status": "RUNNING" if bot_id else "DISABLED",
        }
    except RiskBlocked as e:
        raise _safe_http_error(409, e, "Operation could not be completed") from e
    except HTTPException:
        raise
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


async def _require_feature(db, customer_id: int, feature: str):
    plan, _ = await _subscription_entitlements(db, customer_id)
    if feature not in plan.get("features", []):
        raise HTTPException(403, f"Your Atlas plan does not include {feature}")
    return plan


@app.get("/api/customer/portfolio")
async def customer_portfolio(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=False)
        account = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == profile.id))).scalar_one_or_none()
        wallets = (await db.execute(select(Wallet).where(Wallet.customer_id == profile.id))).scalars().all()
        positions = (await db.execute(select(Position).where(Position.customer_id == profile.id, Position.quantity != 0))).scalars().all()
        bal = await customer_balance(db, profile.id, "USDT")
        return {"equity": float(account.equity) if account else bal["total"], "cash_equity": bal["available"],
                "reserved_margin": bal["trading_reserved"], "withdrawal_reserved": bal["withdrawal_reserved"],
                "wallets":[{"currency":w.currency,"available":(await customer_balance(db, profile.id, w.currency))["available"],"locked":(await customer_balance(db, profile.id, w.currency))["trading_reserved"] + (await customer_balance(db, profile.id, w.currency))["withdrawal_reserved"]} for w in wallets],
                "positions":[{"id":p.id,"exchange":p.exchange,"symbol":p.symbol,"quantity":float(p.quantity),"entry":float(p.average_entry_price),"mark":float(p.mark_price),"unrealized_pnl":float(p.unrealized_pnl)} for p in positions]}


@app.post("/api/customer/smart-trades")
async def create_smart_trade(req: SmartTradeRequest, authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=True)
        await _require_feature(db, profile.id, "smart_trade")
        account = await _get_or_create_customer_trading_account(db, profile)
        if req.side == "BUY" and not (req.stop_loss_price < req.entry_price < req.take_profit_1):
            raise HTTPException(422, "BUY smart trade requires stop < entry < take-profit")
        if req.side == "SELL" and not (req.take_profit_1 < req.entry_price < req.stop_loss_price):
            raise HTTPException(422, "SELL smart trade requires take-profit < entry < stop")
        risk = abs(req.entry_price - req.stop_loss_price) * req.quantity
        if risk > float(account.equity) * settings.risk_per_trade * 2:
            raise HTTPException(409, "Smart trade risk exceeds the account risk guard")
        row=SmartTrade(customer_id=profile.id,trading_account_id=account.id,exchange=req.exchange,symbol=req.symbol,side=req.side,entry_price=req.entry_price,quantity=req.quantity,stop_loss_price=req.stop_loss_price,take_profit_1=req.take_profit_1,take_profit_2=req.take_profit_2,take_profit_3=req.take_profit_3,trailing_stop_pct=req.trailing_stop_pct,breakeven_at_r=req.breakeven_at_r,status="PAPER",notes=req.notes)
        db.add(row); await db.commit()
        return {"id":row.id,"status":row.status,"risk_cash":risk,"message":"Smart trade plan created in paper mode. A Smart Trade live execution controller is not enabled."}


@app.get("/api/customer/smart-trades")
async def list_smart_trades(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        rows=(await db.execute(select(SmartTrade).where(SmartTrade.customer_id==profile.id).order_by(desc(SmartTrade.created_at)).limit(100))).scalars().all()
        return [{"id":r.id,"symbol":r.symbol,"side":r.side,"entry":r.entry_price,"stop":r.stop_loss_price,"tp1":r.take_profit_1,"tp2":r.take_profit_2,"tp3":r.take_profit_3,"status":r.status,"created_at":r.created_at.isoformat()} for r in rows]


@app.post("/api/customer/dca-bots")
async def create_dca_bot(req: DcaBotRequest, authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True)
        await _require_feature(db,profile.id,"dca_bot")
        account=await _get_or_create_customer_trading_account(db,profile)
        total=req.initial_quote + sum(req.safety_order_quote*(req.volume_scale**i) for i in range(req.max_safety_orders))
        if total > float(account.equity):
            raise HTTPException(409,"DCA capital allocation exceeds available trading equity")
        row=DcaBot(customer_id=profile.id,trading_account_id=account.id,exchange=req.exchange,symbol=req.symbol,side=req.side,initial_quote=req.initial_quote,safety_order_quote=req.safety_order_quote,max_safety_orders=req.max_safety_orders,deviation_pct=req.deviation_pct,volume_scale=req.volume_scale,step_scale=req.step_scale,take_profit_pct=req.take_profit_pct,stop_loss_pct=req.stop_loss_pct,trailing_take_profit_pct=req.trailing_take_profit_pct,status="STOPPED",mode="PAPER")
        db.add(row); await db.commit()
        return {"id":row.id,"status":row.status,"maximum_planned_capital":total,"mode":row.mode,"message":"DCA configuration created in paper-only mode. Automatic DCA execution is not enabled."}


@app.get("/api/customer/dca-bots")
async def list_dca_bots(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        rows=(await db.execute(select(DcaBot).where(DcaBot.customer_id==profile.id).order_by(desc(DcaBot.created_at)).limit(100))).scalars().all()
        return [{"id":r.id,"symbol":r.symbol,"side":r.side,"status":r.status,"mode":r.mode,"max_safety_orders":r.max_safety_orders,"initial_quote":r.initial_quote,"safety_order_quote":r.safety_order_quote,"take_profit_pct":r.take_profit_pct,"stop_loss_pct":r.stop_loss_pct} for r in rows]


@app.post("/api/customer/dca-bots/{bot_id}/action")
async def dca_bot_action(bot_id: int, req: BotActionRequest, authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True)
        await _require_feature(db,profile.id,"dca_bot")
        row=(await db.execute(select(DcaBot).where(DcaBot.id==bot_id,DcaBot.customer_id==profile.id).with_for_update())).scalar_one_or_none()
        if not row: raise HTTPException(404,"DCA bot not found")
        if req.action == "START":
            raise HTTPException(409, "DCA execution controller is not enabled; this configuration is paper-only")
        row.status="STOPPED"
        db.add(row); await db.commit()
        return {"id":row.id,"status":row.status,"mode":row.mode}


@app.post("/api/customer/grid-bots")
async def create_grid_bot(req: GridBotRequest, authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True)
        await _require_feature(db,profile.id,"grid_bot")
        account=await _get_or_create_customer_trading_account(db,profile)
        if req.upper_price <= req.lower_price: raise HTTPException(422,"Grid upper price must exceed lower price")
        levels=build_grid(req.lower_price,req.upper_price,req.levels,req.arithmetic)
        planned=req.quote_per_grid*req.levels
        if planned > float(account.equity): raise HTTPException(409,"Grid capital allocation exceeds available trading equity")
        row=GridBot(customer_id=profile.id,trading_account_id=account.id,exchange=req.exchange,symbol=req.symbol,grid_type=req.grid_type,lower_price=req.lower_price,upper_price=req.upper_price,levels=req.levels,arithmetic=req.arithmetic,quote_per_grid=req.quote_per_grid,take_profit_pct=req.take_profit_pct,stop_loss_pct=req.stop_loss_pct,trailing_stop_pct=req.trailing_stop_pct,status="STOPPED",mode="PAPER")
        db.add(row); await db.commit()
        return {"id":row.id,"status":row.status,"mode":row.mode,"planned_capital":planned,"grid_step_pct":grid_profit_pct(req.lower_price,req.upper_price,req.levels,req.arithmetic),"levels":[{"index":x.index,"price":x.price} for x in levels],"message":"Grid created in paper-only mode. Automatic Grid live execution is not enabled."}


@app.get("/api/customer/grid-bots")
async def list_grid_bots(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        await _require_feature(db,profile.id,"grid_bot")
        rows=(await db.execute(select(GridBot).where(GridBot.customer_id==profile.id).order_by(desc(GridBot.created_at)).limit(100))).scalars().all()
        return [{"id":r.id,"symbol":r.symbol,"exchange":r.exchange,"grid_type":r.grid_type,"lower_price":r.lower_price,"upper_price":r.upper_price,"levels":r.levels,"status":r.status,"mode":r.mode} for r in rows]


@app.post("/api/customer/grid-bots/{bot_id}/action")
async def grid_bot_action(bot_id:int, req:BotActionRequest, authorization:str|None=Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True)
        await _require_feature(db,profile.id,"grid_bot")
        row=(await db.execute(select(GridBot).where(GridBot.id==bot_id,GridBot.customer_id==profile.id).with_for_update())).scalar_one_or_none()
        if not row: raise HTTPException(404,"Grid bot not found")
        if req.action == "START":
            raise HTTPException(409, "Grid execution controller is not enabled; this configuration is paper-only")
        row.status="STOPPED"
        db.add(row); await db.commit()
        return {"id":row.id,"status":row.status,"mode":row.mode}


@app.post("/api/customer/broker/deriv/connect")
async def customer_connect_deriv(req: DerivConnectRequest, authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=True)
    if not settings.deriv_app_id:
        raise HTTPException(503, "Atlas Deriv application is not configured")
    broker = DerivBroker(DerivConfig(settings.deriv_app_id, req.api_token.strip(), req.account_id.strip(), timeout_seconds=settings.deriv_timeout_seconds, live=True))
    try:
        summary = await broker.preflight()
        if str(summary.get("account_id") or "") != req.account_id.strip():
            raise HTTPException(400, "Deriv account identity does not match the supplied account ID")
    except (DerivError, DerivUnknown) as exc:
        raise _safe_http_error(400, exc, "Deriv verification failed") from exc
    async with SessionLocal() as db:
        if not summary.get("trade_scope"):
            raise HTTPException(403, "Deriv credential does not present the required trade scope")
        row = (await db.execute(select(CustomerDerivAccount).where(CustomerDerivAccount.customer_id == profile.id).with_for_update())).scalar_one_or_none()
        if row is None:
            row = CustomerDerivAccount(customer_id=profile.id, account_id=req.account_id.strip(), app_id=settings.deriv_app_id, api_token=req.api_token.strip(), can_trade=True, scope_status="TRADE_SCOPE_CONFIRMED", status="VERIFIED", last_verified_at=datetime.now(timezone.utc))
            db.add(row)
        else:
            row.account_id=req.account_id.strip(); row.app_id=settings.deriv_app_id; row.api_token=req.api_token.strip(); row.can_trade=True; row.scope_status="TRADE_SCOPE_CONFIRMED"; row.status="VERIFIED"; row.last_verified_at=datetime.now(timezone.utc)
        await db.commit()
    return {"ok": True, "status": "VERIFIED", "account_id": req.account_id.strip(), "currency": summary.get("currency"), "live_execution_enabled": False, "usage": "credential_preflight_only"}


@app.post("/api/customer/deriv/preflight")
async def customer_deriv_preflight(req: DerivPreflightRequest, authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=True)
        await _require_feature(db, profile.id, "automated_entry_exit")
        row = (await db.execute(select(CustomerDerivAccount).where(CustomerDerivAccount.customer_id == profile.id))).scalar_one_or_none()
    if not row or str(row.status).upper() != "VERIFIED" or not row.can_trade:
        raise HTTPException(409, "Customer Deriv account is not connected and verified")
    broker = DerivBroker(DerivConfig(row.app_id, row.api_token, row.account_id, timeout_seconds=settings.deriv_timeout_seconds, live=True))
    try:
        result = await broker.preflight(req.currency)
        result["account_id"] = row.account_id
        result["broker"] = "deriv"
        result["mode"] = "PRECHECK_ONLY"
        result["live_execution_enabled"] = False
        return result
    except (DerivError, DerivUnknown) as exc:
        raise _safe_http_error(502, exc, "The Deriv practice broker could not complete the preflight request") from exc


@app.post("/api/customer/deriv/execute")
async def customer_deriv_execute(req: DerivTradeRequest, authorization: str | None = Header(default=None)):
    # Authenticate the caller even though execution is fail-closed. This prevents the
    # disabled endpoint from becoming an unauthenticated security-boundary exception
    # and keeps future activation contractually behind customer identity checks.
    await customer_claims(authorization, require_aal2=True)
    raise HTTPException(409, "Deriv live execution is disabled until it is integrated into AtlasRisk's unified live execution outbox and ledger path")


@app.post("/api/admin/deriv/execute")
async def admin_deriv_execute(req: DerivTradeRequest, authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "OPERATIONS")
    raise HTTPException(409, "Deriv live execution is disabled until it is integrated into AtlasRisk's unified live execution outbox and ledger path")


@app.post("/api/admin/arbitrage/binance/live")
async def admin_binance_arbitrage_live(req: BinanceArbitrageLiveRequest, authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "RISK_OFFICER")
    raise HTTPException(409, "Binance arbitrage live execution is disabled until its legs use the unified order outbox, ledger and recovery path")


@app.post("/api/customer/arbitrage/paper")
async def arbitrage_paper(req: ArbitragePaperRequest, authorization: str | None = Header(default=None)):
    if not settings.arbitrage_enabled:
        raise HTTPException(503, "Arbitrage research is disabled")
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        await _require_feature(db,profile.id,"arbitrage")
        account=await _get_or_create_customer_trading_account(db,profile)
        if req.start_quote > min(float(account.equity), settings.arbitrage_max_capital_usdt):
            raise HTTPException(409,"Arbitrage capital exceeds the configured paper allocation")
        quotes={x.symbol:TriangleQuote(x.symbol,x.bid,x.ask,x.bid_qty,x.ask_qty) for x in req.legs}
        result=evaluate_triangle(quotes, tuple((x.symbol,x.side,x.base_asset,x.quote_asset) for x in req.legs), req.start_quote, settings.arbitrage_fee_rate, settings.arbitrage_slippage_buffer_pct, settings.arbitrage_safety_buffer_pct, req.start_asset)
        status="PAPER_CANDIDATE" if result.net_edge_pct >= settings.arbitrage_min_net_edge_pct else "NO_TRADE"
        row=ArbitrageOpportunity(customer_id=profile.id,trading_account_id=account.id,exchange=settings.arbitrage_exchange,path_json=json.dumps([x.symbol for x in req.legs]),start_quote=result.start_quote,end_quote=result.end_quote,gross_edge_pct=result.gross_edge_pct,fees_pct=result.fees_pct,slippage_buffer_pct=result.slippage_buffer_pct,safety_buffer_pct=result.safety_buffer_pct,net_edge_pct=result.net_edge_pct,status=status)
        db.add(row); await db.commit()
        return {"id":row.id,"exchange":row.exchange,"mode":"PAPER","status":status,"path":list(result.path),"start_quote":result.start_quote,"end_quote":result.end_quote,"gross_edge_pct":result.gross_edge_pct,"fees_pct":result.fees_pct,"slippage_buffer_pct":result.slippage_buffer_pct,"safety_buffer_pct":result.safety_buffer_pct,"net_edge_pct":result.net_edge_pct,"reason":result.reason,"executable":bool(result.executable and status=="PAPER_CANDIDATE"),"live_execution_enabled":False}




@app.post("/api/customer/execution-plan")
async def customer_execution_plan(req: ExecutionPlanRequest, authorization: str | None = Header(default=None)):
    """Cost-aware execution planning only; never submits an exchange order."""
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=False)
        await _require_feature(db, profile.id, "arbitrage")
    try:
        levels = [BookLevel(float(x["price"]), float(x["quantity"])) for x in req.levels]
        plan = build_execution_plan(
            side=req.side, quantity=req.quantity, best_price=req.best_price, levels=levels,
            maker_fee_bps=req.maker_fee_bps, taker_fee_bps=req.taker_fee_bps,
            latency_ms=req.latency_ms, short_term_vol_bps_per_s=req.short_term_vol_bps_per_s,
            max_adverse_bps=req.max_adverse_bps, urgency=req.urgency,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _safe_http_error(400, exc, "Invalid request") from exc
    return {**plan.__dict__, "execution_authority": False, "mode": "RESEARCH_ONLY"}


@app.get("/api/customer/arbitrage/opportunities")
async def list_arbitrage_opportunities(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        await _require_feature(db,profile.id,"arbitrage")
        rows=(await db.execute(select(ArbitrageOpportunity).where(ArbitrageOpportunity.customer_id==profile.id).order_by(desc(ArbitrageOpportunity.created_at)).limit(100))).scalars().all()
        return [{"id":r.id,"exchange":r.exchange,"path":json.loads(r.path_json or "[]"),"gross_edge_pct":r.gross_edge_pct,"fees_pct":r.fees_pct,"net_edge_pct":r.net_edge_pct,"status":r.status,"created_at":r.created_at.isoformat()} for r in rows]


@app.post("/api/customer/webhooks")
async def create_customer_webhook(req:WebhookCreateRequest, authorization:str|None=Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True)
        await _require_feature(db,profile.id,"webhooks")
        secret=uuid.uuid4().hex+uuid.uuid4().hex
        exists=(await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.customer_id==profile.id,WebhookEndpoint.name==req.name))).scalar_one_or_none()
        if exists: raise HTTPException(409,"Webhook name already exists")
        row=WebhookEndpoint(customer_id=profile.id,name=req.name,secret_hash=hashlib.sha256(secret.encode()).hexdigest(),status="ACTIVE")
        db.add(row); await db.commit()
        return {"id":row.id,"name":row.name,"secret":secret,"warning":"Store this secret now. Atlas never displays it again."}


@app.get("/api/customer/webhooks")
async def list_customer_webhooks(authorization:str|None=Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        await _require_feature(db,profile.id,"webhooks")
        rows=(await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.customer_id==profile.id).order_by(desc(WebhookEndpoint.created_at)))).scalars().all()
        return [{"id":r.id,"name":r.name,"status":r.status,"created_at":r.created_at.isoformat(),"last_used_at":r.last_used_at.isoformat() if r.last_used_at else None,"url":f"/api/webhooks/{r.id}"} for r in rows]


@app.post("/api/webhooks/{endpoint_id}")
async def receive_customer_webhook(endpoint_id:int, request:Request, x_atlas_webhook_token: str | None = Header(default=None), x_atlas_event_id:str|None=Header(default=None)):
    raw=await request.body()
    async with SessionLocal() as db:
        endpoint=(await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.id==endpoint_id,WebhookEndpoint.status=="ACTIVE"))).scalar_one_or_none()
        if not endpoint: raise HTTPException(404,"Webhook endpoint not found")
        if not x_atlas_webhook_token or not hmac.compare_digest(hashlib.sha256(x_atlas_webhook_token.encode()).hexdigest(), endpoint.secret_hash):
            raise HTTPException(401,"Invalid webhook credential")
        event_id=(x_atlas_event_id or hashlib.sha256(raw).hexdigest())[:160]
        existing=(await db.execute(select(WebhookEvent).where(WebhookEvent.endpoint_id==endpoint.id,WebhookEvent.event_id==event_id))).scalar_one_or_none()
        if existing: return {"accepted":True,"duplicate":True,"event_id":event_id}
        try: payload=json.loads(raw.decode("utf-8"))
        except Exception: raise HTTPException(400,"Webhook body must be JSON")
        db.add(WebhookEvent(endpoint_id=endpoint.id,event_id=event_id,payload_json=json.dumps(payload,separators=(",",":")),status="RECEIVED"))
        endpoint.last_used_at=datetime.now(timezone.utc)
        await db.commit()
        return {"accepted":True,"duplicate":False,"event_id":event_id,"action":"RECEIVED_ONLY"}


@app.get("/api/customer/connectors")
async def customer_connectors(authorization:str|None=Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        rows=(await db.execute(select(ExchangeConnector).where(ExchangeConnector.enabled==True).order_by(ExchangeConnector.name))).scalars().all()
        return [{"name":r.name,"market_types":r.market_types.split(","),"capabilities":json.loads(r.capabilities_json or "{}") } for r in rows]


def _scanner_metrics(df):
    close=df.close.astype(float); volume=df.volume.astype(float)
    ema20=close.ewm(span=20,adjust=False).mean().iloc[-1]; ema50=close.ewm(span=50,adjust=False).mean().iloc[-1]
    delta=close.diff(); gain=delta.clip(lower=0).rolling(14).mean(); loss=(-delta.clip(upper=0)).rolling(14).mean(); rs=gain/loss.replace(0,pd.NA); rsi=float((100-(100/(1+rs))).iloc[-1]) if pd.notna(rs.iloc[-1]) else 50.0
    atr=(df.high-df.low).rolling(14).mean().iloc[-1]; last=float(close.iloc[-1]); vol_ratio=float(volume.iloc[-1]/max(volume.rolling(20).mean().iloc[-1],1e-12))
    trend=1 if ema20>ema50 else -1
    momentum=1 if last>float(close.iloc[-2]) else -1
    breakout=1 if last>=float(close.iloc[-21:-1].max()) else (-1 if last<=float(close.iloc[-21:-1].min()) else 0)
    score=max(-1,min(1,0.45*trend+0.25*momentum+0.2*breakout+0.1*(1 if 50<=rsi<=70 else -1 if rsi>80 or rsi<30 else 0)))
    return {"price":last,"rsi":rsi,"ema20":float(ema20),"ema50":float(ema50),"atr":float(atr),"volume_ratio":vol_ratio,"score":float(score),"signal":"LONG" if score>=0.35 else "SHORT" if score<=-0.35 else "WATCH"}


@app.get("/api/customer/market-scanner")
async def customer_market_scanner(exchange: str="binance", symbols: str="BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,XRP/USDT:USDT", authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        await _require_feature(db,profile.id,"market_scanner")
    requested=[x.strip() for x in symbols.split(",") if x.strip()][:20]
    async def one(sym):
        try:
            df=await asyncio.to_thread(fetch_crypto,sym,exchange,"15m",30,True)
            return {"symbol":sym,**_scanner_metrics(df)}
        except Exception as exc:
            return {"symbol":sym,"signal":"ERROR","error":str(exc)[:180]}
    results=await asyncio.gather(*(one(s) for s in requested))
    return {"exchange":exchange,"timeframe":"15m","results":sorted(results,key=lambda x: abs(float(x.get("score",0))),reverse=True)}


@app.get("/api/customer/market-intelligence")
async def customer_market_intelligence(authorization: str | None = Header(default=None)):
    """Fresh research context: prices, macro headlines, trend state and risk flags.

    This endpoint is advisory/research-only. It never creates orders or changes risk limits.
    """
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db)
        from .market_intelligence import gather_market_intelligence
        symbols = [s.strip() for s in settings.research_symbols.split(",") if s.strip()]
        intelligence = await gather_market_intelligence(
            symbols=symbols, yahoo_period="1y", alpha_vantage_api_key=settings.alpha_vantage_api_key
        )
        intelligence.pop("histories", None)
        intelligence["customer_id"] = profile.id
        return intelligence


@app.post("/api/customer/alerts")
async def create_alert(req: AlertRequest, authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True)
        await _require_feature(db,profile.id,"alerts")
        row=CustomerAlert(customer_id=profile.id,alert_type=req.alert_type,symbol=req.symbol,threshold=req.threshold,condition=req.condition,channel=req.channel,message=req.message,status="CONFIGURED")
        db.add(row); await db.commit()
        return {"id":row.id,"status":row.status,"message":"Alert configuration saved. Automatic alert evaluation is not currently enabled; external delivery is also unavailable until a notification worker is configured."}


@app.get("/api/customer/alerts")
async def list_alerts(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        rows=(await db.execute(select(CustomerAlert).where(CustomerAlert.customer_id==profile.id).order_by(desc(CustomerAlert.created_at)).limit(100))).scalars().all()
        return [{"id":r.id,"type":r.alert_type,"symbol":r.symbol,"threshold":r.threshold,"condition":r.condition,"channel":r.channel,"status":r.status,"message":r.message,"triggered_at":r.triggered_at.isoformat() if r.triggered_at else None} for r in rows]


@app.post("/api/customer/strategy-lab/candidates")
async def create_strategy_candidate(req: StrategyLabRequest, authorization: str | None = Header(default=None)):
    _assert_established_noncrypto(MarketRequest(asset=req.asset, symbol=req.symbol, exchange=req.exchange, timeframe=req.timeframe, days=req.days))
    if req.asset in {"forex", "commodity"}:
        req.symbol = _normalize_oanda_instrument(req.symbol); req.exchange = "oanda"
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True)
        await _require_feature(db, profile.id, "strategy_builder")
        try:
            generated = await generate_strategy_draft(
                prompt=req.prompt,
                name=req.name,
                asset=req.asset,
                symbol=req.symbol,
                timeframe=req.timeframe,
            )
        except AIProviderError as exc:
            raise _safe_http_error(503, exc, "Strategy generation is temporarily unavailable") from exc
        spec = generated["strategy"]
        spec["requested_market"] = {
            "asset": req.asset,
            "symbol": req.symbol,
            "exchange": req.exchange,
            "timeframe": req.timeframe,
        }
        spec["live_authority"] = False
        spec["ai_provider"] = generated["ai"]
        row=StrategyCandidate(customer_id=profile.id,name=req.name,asset=req.asset,symbol=req.symbol,exchange=req.exchange,timeframe=req.timeframe,spec_json=json.dumps(spec,separators=(",",":")))
        db.add(row); await db.commit(); await db.refresh(row)
        return {"id":row.id,"status":row.status,"spec":spec,"next":"RUN_BACKTEST"}

@app.post("/api/customer/strategy-lab/candidates/{candidate_id}/validate")
async def validate_strategy_candidate(candidate_id:int, authorization:str|None=Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True)
        row=(await db.execute(select(StrategyCandidate).where(StrategyCandidate.id==candidate_id,StrategyCandidate.customer_id==profile.id).with_for_update())).scalar_one_or_none()
        if not row: raise HTTPException(404,"Strategy candidate not found")
        req=CustomerBotStartRequest(asset=row.asset,symbol=row.symbol,exchange=row.exchange,timeframe=row.timeframe,days=365,autonomous=False)
    try:
        df=await _fetch_customer_oanda_data(profile.id,req) if row.asset in {"forex","commodity"} else await asyncio.to_thread(market_data,req)
        result=await asyncio.to_thread(backtest_all_strategies,df,StrategyConfig(),5.5,2.0,True,row.asset,5,800,settings.research_ai_threshold)
        rows=result.get("strategies",[])
        spec=json.loads(row.spec_json or "{}")
        family_map={"TREND":"trend","MOMENTUM":"momentum","BREAKOUT":"breakout","MEAN_REVERSION":"mean_reversion","ENSEMBLE":"ensemble"}
        family=str(spec.get("strategy_family") or "ENSEMBLE").upper()
        selected_name=family_map.get(family,"ensemble")
        selected=next((x for x in rows if x.get("strategy")==selected_name),None) or {}
        gate={"strategy_family":family,"validated_component":selected_name,"evidence_level":(selected.get("evidence") or {}).get("evidence_level"),"sharpe":float(selected.get("sharpe",0)),"max_drawdown":float(selected.get("max_drawdown",-1)),"trades":int(selected.get("trades",0)),"total_return":float(selected.get("total_return",0))}
        oos=result.get("validation",{}).get("per_strategy_oos",{}).get(selected_name,{})
        folds=oos.get("folds",[]) or []
        positive_ratio=(sum(1 for f in folds if float(f.get("total_return",0))>0)/len(folds)) if folds else 0.0
        gate["oos_total_return"]=float(oos.get("oos_total_return",-1))
        gate["oos_positive_fold_ratio"]=positive_ratio
        oos_gate=oos_promotion_gate(oos,min_folds=settings.strategy_oos_min_folds,min_total_return=settings.research_min_oos_total_return,min_positive_fold_ratio=settings.research_min_oos_positive_fold_ratio,max_negative_fold_return=settings.strategy_oos_max_negative_fold_return,require_last_fold_positive=settings.strategy_oos_require_last_fold_positive,min_sharpe=settings.strategy_oos_min_sharpe,max_drawdown=settings.strategy_oos_max_drawdown,min_trades=settings.strategy_oos_min_trades)
        gate["oos_gate"]=oos_gate
        gate["robustness_monte_carlo"]=monte_carlo_bootstrap([float(x.get("total_return",0)) for x in (oos.get("folds") or [])],trials=500)
        passed=(gate["sharpe"]>=settings.adaptive_min_sharpe and gate["max_drawdown"]>=-abs(settings.adaptive_max_drawdown) and gate["trades"]>=settings.adaptive_min_trades and gate["total_return"]>=settings.adaptive_min_total_return and oos_gate["passed"])
    except Exception as exc:
        result={"status":"ERROR","error":str(exc)}; gate={}; passed=False; oos={}
    async with SessionLocal() as db:
        row=(await db.execute(select(StrategyCandidate).where(StrategyCandidate.id==candidate_id,StrategyCandidate.customer_id==profile.id).with_for_update())).scalar_one()
        row.backtest_json=json.dumps(result,default=str); row.oos_json=json.dumps(oos,default=str); row.status="VALIDATED" if passed else "REJECTED"; row.live_approved=False
        # Keep an immutable history of every attempt; the candidate row only holds the latest.
        prior=(await db.execute(select(func.count(StrategyCandidateRun.id)).where(StrategyCandidateRun.candidate_id==candidate_id))).scalar_one()
        attempt=int(prior or 0)+1
        db.add(StrategyCandidateRun(candidate_id=candidate_id,attempt=attempt,backtest_json=json.dumps(result,default=str),oos_json=json.dumps(oos,default=str),gate_json=json.dumps(gate,default=str),passed=bool(passed)))
        await db.commit()
    return {"candidate_id":candidate_id,"attempt":attempt,"status":"VALIDATED" if passed else "REJECTED","gate":gate,"oos":oos,"promotion_requires_explicit_live_approval":True,"validation_scope":"Atlas-supported strategy family; AI custom conditions remain a research specification unless separately compiled.","real_money_execution":False}

@app.get("/api/customer/strategy-lab/candidates/{candidate_id}/runs")
async def list_strategy_candidate_runs(candidate_id:int, authorization:str|None=Header(default=None)):
    """Validation history for one candidate, newest first, with deltas vs the previous attempt."""
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        owned=(await db.execute(select(StrategyCandidate.id).where(StrategyCandidate.id==candidate_id,StrategyCandidate.customer_id==profile.id))).scalar_one_or_none()
        if owned is None: raise HTTPException(404,"Strategy candidate not found")
        rows=(await db.execute(select(StrategyCandidateRun).where(StrategyCandidateRun.candidate_id==candidate_id).order_by(desc(StrategyCandidateRun.attempt)).limit(50))).scalars().all()
        out=[]
        for r in rows:
            gate=json.loads(r.gate_json or "{}")
            out.append({"attempt":r.attempt,"passed":r.passed,"gate":gate,"created_at":r.created_at.isoformat()})
        for i in range(len(out)-1):
            cur,prev=out[i]["gate"],out[i+1]["gate"]
            out[i]["delta_vs_previous"]={k:round(float(cur.get(k,0))-float(prev.get(k,0)),6) for k in ("sharpe","max_drawdown","total_return","oos_total_return") if k in cur and k in prev}
        return out

@app.post("/api/customer/strategy-lab/candidates/{candidate_id}/approve-live")
async def approve_strategy_candidate(candidate_id:int, authorization:str|None=Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True)
        row=(await db.execute(select(StrategyCandidate).where(StrategyCandidate.id==candidate_id,StrategyCandidate.customer_id==profile.id).with_for_update())).scalar_one_or_none()
        if not row: raise HTTPException(404,"Strategy candidate not found")
        if row.status!="VALIDATED": raise HTTPException(409,"Only validated candidates can be approved")
        row.live_approved=True; row.status="VALIDATED"; await db.commit()
        await _audit("STRATEGY_CANDIDATE_LIVE_APPROVED",{"candidate_id":candidate_id,"customer_id":profile.id})
        return {"candidate_id":candidate_id,"live_approved":True,"execution_authority":False,"note":"Approval permits use by an autonomous bot; risk/execution gates remain authoritative."}

@app.get("/api/customer/strategy-lab/candidates")
async def list_strategy_candidates(authorization:str|None=Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        rows=(await db.execute(select(StrategyCandidate).where(StrategyCandidate.customer_id==profile.id).order_by(desc(StrategyCandidate.created_at)).limit(50))).scalars().all()
        return [{"id":r.id,"name":r.name,"asset":r.asset,"symbol":r.symbol,"exchange":r.exchange,"timeframe":r.timeframe,"status":r.status,"live_approved":r.live_approved,"created_at":r.created_at.isoformat()} for r in rows]

@app.post("/api/customer/executors")
async def create_customer_executor(req:ExecutorCreateRequest, authorization:str|None=Header(default=None)):
    if req.asset in {"forex","commodity"}: req.exchange="oanda"; req.symbol=_normalize_oanda_instrument(req.symbol)
    cfg=ExecutorConfig(kind=req.kind,total_quantity=req.total_quantity,slices=req.slices,interval_seconds=req.interval_seconds,max_slippage_bps=req.max_slippage_bps,stop_loss_price=req.stop_loss_price,take_profit_price=req.take_profit_price)
    try: validate=build_executor_plan(cfg,market_price=1.0)
    except ExecutorValidationError as exc: raise _safe_http_error(422, exc, "Invalid executor configuration") from exc
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True); account=await _get_or_create_customer_trading_account(db,profile)
        if req.mode == "LIVE":
            if req.asset in {"forex", "commodity"}:
                raise HTTPException(403, "OANDA customer automation is demo/paper-only; live Forex and commodities are disabled")
            plan,_=await _subscription_entitlements(db,profile.id); state=await db.get(AppState,1)
            if not plan.get("live") or not settings.customer_live_trading_enabled or not state or state.kill_switch or not state.live_enabled or settings.paper_trading:
                raise HTTPException(403,"Live executor is not currently permitted")
            try:
                await assert_live_system_enabled(
                    db, asset=req.asset, customer_id=profile.id, exchange=req.exchange,
                    side=req.side.lower(), quantity=max(0.000001, float(req.total_quantity)), reduce_only=False,
                )
            except LiveExecutionBlocked as exc:
                raise _safe_http_error(403, exc, "Live executor cannot be armed") from exc
        config={**validate,"side":req.side}
        row=TradeExecutor(customer_id=profile.id,trading_account_id=account.id,kind=req.kind,asset=req.asset,exchange=req.exchange,symbol=req.symbol,timeframe=req.timeframe,config_json=json.dumps(config,separators=(",",":")),target_quantity=req.total_quantity,status="ARMED",mode=req.mode,live_approved=(req.mode=="LIVE"),next_run_at=datetime.now(timezone.utc))
        db.add(row); await db.commit(); await db.refresh(row)
        return {"id":row.id,"status":row.status,"kind":row.kind,"plan":config,"execution_authority":bool(row.mode == "LIVE" and row.live_approved)}

@app.get("/api/customer/executors")
async def list_customer_executors(authorization:str|None=Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        rows=(await db.execute(select(TradeExecutor).where(TradeExecutor.customer_id==profile.id).order_by(desc(TradeExecutor.created_at)).limit(100))).scalars().all()
        return [{"id":r.id,"kind":r.kind,"asset":r.asset,"exchange":r.exchange,"symbol":r.symbol,"status":r.status,"mode":r.mode,"live_approved":r.live_approved,"executed_quantity":r.executed_quantity,"target_quantity":r.target_quantity,"next_run_at":r.next_run_at.isoformat() if r.next_run_at else None,"last_error":r.last_error} for r in rows]

@app.post("/api/customer/executors/{executor_id}/action")
async def customer_executor_action(executor_id:int, req:BotActionRequest, authorization:str|None=Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True)
        row=(await db.execute(select(TradeExecutor).where(TradeExecutor.id==executor_id,TradeExecutor.customer_id==profile.id).with_for_update())).scalar_one_or_none()
        if not row: raise HTTPException(404,"Executor not found")
        action=req.action.upper()
        if action=="STOP": row.status="STOPPED"; row.next_run_at=None
        elif action=="START":
            if str(row.mode).upper() == "LIVE":
                cfg = json.loads(row.config_json or "{}")
                try:
                    await assert_live_system_enabled(
                        db, asset=row.asset, customer_id=profile.id, exchange=row.exchange,
                        side=str(cfg.get("side", "buy")).lower(), quantity=max(0.000001, float(row.target_quantity or 0)), reduce_only=False,
                    )
                except LiveExecutionBlocked as exc:
                    raise _safe_http_error(403, exc, "Live executor cannot be started") from exc
            row.status="ARMED"; row.next_run_at=datetime.now(timezone.utc); row.last_error=""
        elif action=="APPROVE_LIVE":
            if row.asset in {"forex", "commodity"}:
                raise HTTPException(403, "OANDA customer automation is demo/paper-only; live Forex and commodities are disabled")
            plan,_=await _subscription_entitlements(db,profile.id); state=await db.get(AppState,1)
            if not plan.get("live") or not settings.customer_live_trading_enabled or not state or state.kill_switch or not state.live_enabled or settings.paper_trading:
                raise HTTPException(403,"Live execution is not currently permitted")
            row.mode="LIVE"; row.live_approved=True; row.status="ARMED"; row.next_run_at=datetime.now(timezone.utc)
        else: raise HTTPException(422,"Unsupported executor action")
        await db.commit(); return {"id":row.id,"status":row.status}

@app.post("/api/customer/strategy-builder")
async def strategy_builder(req: StrategyBuilderRequest, authorization: str | None = Header(default=None)):
    """Compatibility alias for Strategy Lab candidate creation.

    This endpoint used to create a StrategyDraft row that had no backtest, validation or
    promotion path at all (a dead end: its own response told the user to "run backtest"
    but nothing accepted a StrategyDraft). It now creates a StrategyCandidate, which has
    the full validate -> approve-live lifecycle. The response keeps the legacy keys.
    """
    # Keep the compatibility route explicitly authenticated at the HTTP boundary rather than
    # relying on create_strategy_candidate() as an implicit security side effect.
    await customer_claims(authorization, require_aal2=True)
    lab_req = StrategyLabRequest(name=req.name, prompt=req.prompt, asset=req.asset, symbol=req.symbol,
                                 exchange=req.exchange, timeframe=req.timeframe)
    created = await create_strategy_candidate(lab_req, authorization)
    spec = created["spec"]
    return {
        "id": created["id"],
        "candidate_id": created["id"],
        "name": req.name,
        "strategy": spec,
        "ai": spec.get("ai_provider"),
        "status": created["status"],
        "next_step": "POST /api/customer/strategy-lab/candidates/{id}/validate to backtest and walk-forward validate this strategy.".replace("{id}", str(created["id"])),
    }


@app.post("/api/customer/strategy-builder/{draft_id}/promote")
async def promote_strategy_draft(draft_id: int, authorization: str | None = Header(default=None)):
    """Rescue a legacy StrategyDraft by converting it into a validatable StrategyCandidate."""
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=True)
        await _require_feature(db,profile.id,"strategy_builder")
        draft=(await db.execute(select(StrategyDraft).where(StrategyDraft.id==draft_id,StrategyDraft.customer_id==profile.id).with_for_update())).scalar_one_or_none()
        if not draft: raise HTTPException(404,"Strategy draft not found")
        if draft.status=="PROMOTED": raise HTTPException(409,"Draft was already promoted")
        spec=json.loads(draft.strategy_json or "{}")
        market=spec.get("requested_market") or {}
        asset=str(market.get("asset") or "crypto")
        if asset not in {"crypto","forex","commodity"}: asset="crypto"
        timeframe=str(market.get("timeframe") or "1h")
        if timeframe not in {"5m","15m","30m","1h","4h","1d"}: timeframe="1h"
        symbol=str(market.get("symbol") or "BTC/USDT:USDT")[:80]
        exchange=str(market.get("exchange") or ("oanda" if asset!="crypto" else "binance"))[:50]
        spec["requested_market"]={"asset":asset,"symbol":symbol,"exchange":exchange,"timeframe":timeframe}
        spec["live_authority"]=False
        spec["promoted_from_draft_id"]=draft.id
        row=StrategyCandidate(customer_id=profile.id,name=draft.name,asset=asset,symbol=symbol,exchange=exchange,timeframe=timeframe,spec_json=json.dumps(spec,separators=(",",":")))
        draft.status="PROMOTED"
        db.add(row); await db.commit(); await db.refresh(row)
        return {"candidate_id":row.id,"draft_id":draft.id,"status":row.status,"next":"RUN_BACKTEST"}


@app.get("/api/customer/strategy-builder")
async def list_strategy_drafts(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile,_=await get_customer(authorization,db,require_aal2=False)
        rows=(await db.execute(select(StrategyDraft).where(StrategyDraft.customer_id==profile.id).order_by(desc(StrategyDraft.created_at)).limit(50))).scalars().all()
        return [{"id":r.id,"name":r.name,"prompt":r.prompt,"strategy":json.loads(r.strategy_json or "{}"),"status":r.status,"created_at":r.created_at.isoformat()} for r in rows]


@app.post("/api/customer/withdrawals")
async def customer_create_withdrawal(req: CustomerWithdrawalCreate, authorization: str | None = Header(default=None), x_withdrawal_step_up: str | None = Header(default=None)):
    if not settings.withdrawals_enabled:
        raise HTTPException(403, "Withdrawals are currently disabled")
    if req.network.upper() != "TRON" or not _tron_base58check_valid(req.destination):
        raise HTTPException(422, "A valid TRON address is required")
    if req.amount > settings.withdrawal_max_amount:
        raise HTTPException(409, "Withdrawal exceeds the configured maximum")
    if req.amount < 1.0:
        raise HTTPException(409, "Minimum USDT withdrawal is 1.0 USDT")
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db, require_aal2=True)
        requested_fp = destination_fingerprint(req.destination.strip(), "USDT", req.network.upper())
        requested_stepup_digest = proposal_digest(request_id="STEPUP", amount=req.amount, currency="USDT", destination=req.destination.strip(), tag=req.destination_tag or "", network=req.network.upper(), provider=settings.payout_provider)
        parsed_stepup = _parse_stepup_token(x_withdrawal_step_up, profile.auth_user_id, "withdrawal", requested_fp, requested_stepup_digest)
        if not parsed_stepup:
            raise HTTPException(403, "Fresh OTP step-up verification is required before withdrawal")
        jti, _, _ = parsed_stepup
        stepup = (await db.execute(select(WithdrawalStepUpToken).where(
            WithdrawalStepUpToken.jti == jti,
            WithdrawalStepUpToken.auth_user_id == profile.auth_user_id,
            WithdrawalStepUpToken.purpose == "withdrawal",
            WithdrawalStepUpToken.destination_fingerprint == requested_fp,
            WithdrawalStepUpToken.proposal_digest == requested_stepup_digest,
            WithdrawalStepUpToken.used_at.is_(None),
            WithdrawalStepUpToken.expires_at >= datetime.now(timezone.utc),
        ).with_for_update())).scalar_one_or_none()
        if not stepup or not hmac.compare_digest(stepup.token_hash, hashlib.sha256(x_withdrawal_step_up.encode()).hexdigest()):
            raise HTTPException(403, "Fresh OTP step-up verification is required before withdrawal")
        stepup.used_at = datetime.now(timezone.utc)
        wallet = (await db.execute(select(Wallet).where(
            Wallet.customer_id == profile.id, Wallet.currency == "USDT", Wallet.network == "TRON",
            Wallet.status == "ACTIVE"
        ).with_for_update())).scalar_one_or_none()
        if not wallet:
            raise HTTPException(404, "USDT TRON trading wallet not found")
        if req.destination.strip() == wallet.deposit_address:
            raise HTTPException(409, "Withdrawal destination must be external to your deposit address")
        destination_policy = await register_or_check_destination(
            db, customer_id=profile.id, destination=req.destination.strip(), currency="USDT", network="TRON"
        )
        if not destination_policy["allowed"]:
            await db.commit()
            raise HTTPException(409, f"Withdrawal destination is not yet trusted: {destination_policy['reason']}; ready_at={destination_policy.get('ready_at')}")
        balance = await customer_balance(db, profile.id, "USDT")
        if balance["available"] < req.amount:
            raise HTTPException(409, "Insufficient available USDT balance")
        trading_account = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == profile.id).with_for_update())).scalar_one_or_none()
        if trading_account:
            open_positions = (await db.execute(select(Position).where(Position.customer_id == profile.id, Position.quantity != 0))).scalars().all()
            if open_positions or trading_account.reserved_margin > 0:
                raise HTTPException(409, "Close open trading positions before withdrawing allocated trading capital")
            # Compare and debit through Decimal so a withdrawal for exactly the available balance
            # can't be wrongly rejected (or a slightly-too-large one wrongly allowed) by float
            # representation error, and so repeated withdrawals don't accumulate float drift in
            # cash_equity/equity/peak_equity/daily_start_equity.
            amount_d = Decimal(str(req.amount))
            if amount_d > Decimal(str(trading_account.cash_equity)):
                raise HTTPException(409, "Withdrawal exceeds unallocated trading-account capital")
            trading_account.cash_equity = quantize_money(trading_account.cash_equity - req.amount)
            trading_account.equity = max(0.0, quantize_money(trading_account.equity - req.amount))
            trading_account.peak_equity = max(trading_account.equity, quantize_money(trading_account.peak_equity - req.amount))
            trading_account.daily_start_equity = max(0.0, quantize_money(trading_account.daily_start_equity - req.amount))
        risk = await score_withdrawal(db, customer_id=profile.id, wallet_balance=balance["available"], amount=req.amount, destination=req.destination, currency="USDT", network="TRON")
        if risk["decision"] == "BLOCK":
            await db.rollback()
            await _audit("CUSTOMER_WITHDRAWAL_BLOCKED", {"customer_id": profile.id, "amount": req.amount, "risk_score": risk["score"], "risk_flags": risk["flags"]})
            raise HTTPException(403, "Withdrawal blocked by the transaction risk engine; contact support")
        request_id = f"cust-wd-{profile.id}-{hashlib.sha256(f'{profile.id}:{datetime.now(timezone.utc).isoformat()}:{req.destination}:{req.amount}'.encode()).hexdigest()[:24]}"
        w = Withdrawal(
            customer_id=profile.id, wallet_id=wallet.id, request_id=request_id,
            account_ref=str(profile.id), amount=req.amount, currency="USDT",
            destination_masked=req.destination[:6] + "…" + req.destination[-6:],
            destination=req.destination.strip(), destination_tag=req.destination_tag or "", network="TRON",
            provider=settings.payout_provider, status="PENDING", risk_score=risk["score"], risk_flags=json.dumps(risk["flags"], separators=(",", ":")),
            required_approvals=2 if settings.withdrawal_dual_approval else 1,
        )
        w.proposal_digest = proposal_digest(request_id=request_id, amount=req.amount, currency="USDT",
            destination=w.destination, tag=w.destination_tag, network="TRON", provider=w.provider)
        await reserve_withdrawal(db, profile.id, req.amount, reference_id=w.request_id)
        await sync_wallet_from_ledger(db, profile.id, "USDT")
        ledger_balance = await customer_balance(db, profile.id, "USDT")
        if trading_account:
            trading_account.cash_equity = ledger_balance["available"] + ledger_balance["trading_reserved"]
            trading_account.equity = max(0.0, trading_account.cash_equity + trading_account.realized_pnl + trading_account.unrealized_pnl)
        db.add(w)
        await db.commit()
        await db.refresh(w)
    await _audit("CUSTOMER_WITHDRAWAL_REQUESTED", {"id": w.id, "customer_id": profile.id, "amount": req.amount, "currency": "USDT", "network": "TRON"})
    return {"ok": True, "id": w.id, "request_id": w.request_id, "status": w.status,
            "amount": w.amount, "currency": w.currency, "network": w.network,
            "destination_masked": w.destination_masked, "required_approvals": w.required_approvals}


@app.get("/api/customer/withdrawals")
async def customer_withdrawals(authorization: str | None = Header(default=None)):
    async with SessionLocal() as db:
        profile, _ = await get_customer(authorization, db)
        rows = (await db.execute(select(Withdrawal).where(Withdrawal.customer_id == profile.id)
                                 .order_by(desc(Withdrawal.created_at)).limit(100))).scalars().all()
        return [{"id": w.id, "request_id": w.request_id, "amount": w.amount, "currency": w.currency,
                 "network": w.network, "destination_masked": w.destination_masked, "status": w.status,
                 "approval_count": w.approval_count, "required_approvals": w.required_approvals,
                 "provider_id": w.provider_id, "created_at": w.created_at.isoformat(),
                 "updated_at": w.updated_at.isoformat() if w.updated_at else None,
                 "rejection_reason": w.rejection_reason} for w in rows]


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    checks = {}
    try:
        async with SessionLocal() as db:
            await db.get(AppState, 1)
        checks["database"] = True
    except Exception:
        checks["database"] = False

    try:
        await _assert_database_migrations_current()
        checks["migrations_current"] = True
    except Exception:
        checks["migrations_current"] = False

    checks["distributed_rate_limiter"] = await check_redis()
    recovery_config_ok = (not settings.require_backup_recovery_config) or bool(settings.backup_recovery_url) or settings.environment != "production"
    checks["recovery_configured"] = recovery_config_ok
    if settings.environment == "development":
        checks["admin_auth"] = True
    else:
        allowed_admins = [x.strip() for x in str(settings.admin_supabase_user_ids or "").split(",") if x.strip()]
        checks["admin_auth"] = bool(allowed_admins)
        if checks["admin_auth"]:
            try:
                checks["admin_auth"] = any(bool(await get_roles(uid)) for uid in allowed_admins)
            except Exception:
                checks["admin_auth"] = False
    checks["secret_configured"] = bool(settings.secret_key) or settings.environment == "development"
    try:
        from .crypto import validate_encryption_config
        validate_encryption_config()
        checks["encryption_configured"] = True
    except Exception:
        checks["encryption_configured"] = False

    # Multi-instance execution is safe only when the persisted fencing control plane exists;
    # a Cloud Run single-process assumption is not a production safety boundary.
    try:
        async with SessionLocal() as db:
            lease_row = await db.get(LiveExecutionLease, 1)
        checks["execution_fencing"] = lease_row is not None
    except Exception:
        checks["execution_fencing"] = False
    checks["single_worker"] = True  # legacy informational field; DB fencing supersedes it.
    live_configured = bool(settings.live_trading_enabled and not settings.paper_trading
                          and not settings.broker_sandbox
                          and settings.exchange_api_key and settings.exchange_api_secret)
    checks["safe_trading_config"] = bool(settings.paper_trading or live_configured)
    checks["sandbox_when_paper"] = (not settings.paper_trading) or settings.broker_sandbox is True

    signer_config_ok = (not settings.external_custody_signer_required) or bool(
        settings.external_custody_signer_url and settings.external_custody_signer_hmac_secret
    )
    checks["custody_signer_configured"] = signer_config_ok
    payout_provider = str(settings.payout_provider or "disabled").lower()
    payout_config_ok = not settings.payout_live_enabled or (
        payout_provider != "disabled" and payout_provider != "ccxt" and signer_config_ok
    )
    checks["payout_boundary"] = payout_config_ok
    checks["external_security_audit"] = (
        settings.external_security_audit_enabled if settings.external_security_audit_required else True
    )

    # Meta-labeling is safe for live use only because the gate now predicts the
    # current, unlabeled bar from models trained strictly on completed labels.
    checks["meta_label_live_safe"] = True

    return {"ready": all(checks.values()), "checks": checks}


@app.get("/metrics")
async def metrics(x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    if settings.metrics_require_admin:
        await auth(x_admin_token, authorization)
    body, content_type = metrics_response()
    return Response(content=body, media_type=content_type)


@app.get("/api/state")
async def state(x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    async with SessionLocal() as db:
        s = await db.get(AppState, 1)
        positions = (await db.execute(select(Position).where(Position.quantity != 0))).scalars().all()
        return {
            "mode": s.mode, "equity": s.equity, "cash_equity": s.cash_equity,
            "peak_equity": s.peak_equity,
            "drawdown": (1 - s.equity / s.peak_equity if s.peak_equity else 0),
            "daily_loss": (1 - s.equity / s.daily_start_equity if s.daily_start_equity else 0),
            "realized_pnl": s.realized_pnl, "unrealized_pnl": s.unrealized_pnl,
            "kill_switch": s.kill_switch, "live_enabled": s.live_enabled,
            "open_positions": [{"symbol": p.symbol, "quantity": p.quantity,
                                "entry": p.average_entry_price, "mark": p.mark_price,
                                "unrealized_pnl": p.unrealized_pnl} for p in positions],
        }


@app.get("/api/trades")
async def trades(x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    async with SessionLocal() as db:
        rows = (await db.execute(select(Trade).order_by(desc(Trade.created_at)).limit(200))).scalars().all()
        return [{"id": r.id, "signal_id": r.signal_id, "client_order_id": r.client_order_id,
                 "broker_order_id": r.broker_order_id, "exchange": r.exchange, "symbol": r.symbol,
                 "side": r.side, "quantity": r.quantity, "requested_quantity": r.requested_quantity,
                 "filled_quantity": r.filled_quantity, "remaining_quantity": r.remaining_quantity,
                 "requested_price": r.requested_price, "average_fill_price": r.average_fill_price,
                 "fee": r.fee, "notional": r.notional, "mode": r.mode, "status": r.status,
                 "reason": r.reason, "error": r.error, "stop_loss_price": r.stop_loss_price,
                 "take_profit_price": r.take_profit_price, "created_at": r.created_at.isoformat()} for r in rows]


@app.get("/api/admin/withdrawals")
async def list_withdrawals(status: str = "PENDING", x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "READ_ONLY")
    if not settings.withdrawals_enabled:
        raise HTTPException(403, "Withdrawal administration is disabled")
    allowed = {"PENDING", "PARTIALLY_APPROVED", "APPROVED", "SUBMITTING", "SUBMITTED", "UNKNOWN", "FAILED", "REJECTED", "RELEASED", "ALL"}
    if status not in allowed:
        raise HTTPException(400, "Invalid withdrawal status")
    async with SessionLocal() as db:
        q = select(Withdrawal).order_by(desc(Withdrawal.created_at)).limit(500)
        if status != "ALL":
            q = q.where(Withdrawal.status == status)
        rows = (await db.execute(q)).scalars().all()
        customer_ids = {r.customer_id for r in rows if r.customer_id}
        profiles = {}
        if customer_ids:
            profiles = {p.id: p for p in (await db.execute(select(CustomerProfile).where(CustomerProfile.id.in_(customer_ids)))).scalars().all()}
        return [{
            "id": r.id, "request_id": r.request_id, "customer_id": r.customer_id,
            "customer_email": profiles.get(r.customer_id).email if r.customer_id in profiles else "",
            "account_ref": r.account_ref,
            "amount": r.amount, "currency": r.currency, "destination_masked": r.destination_masked,
            "status": r.status, "risk_score": r.risk_score,
            "risk_flags": json_loads(r.risk_flags), "required_approvals": r.required_approvals,
            "approval_count": r.approval_count, "first_approved_by": r.first_approved_by,
            "provider": r.provider, "provider_id": r.provider_id, "provider_status": r.provider_status,
            "execution_status": r.status, "proposal_digest": r.proposal_digest, "execution_operator": r.execution_operator,
            "second_approved_by": r.second_approved_by, "rejected_by": r.rejected_by,
            "rejection_reason": r.rejection_reason, "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        } for r in rows]


@app.post("/api/admin/withdrawals")
async def create_withdrawal(req: WithdrawalCreate, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "TREASURY")
    if not settings.withdrawals_enabled:
        raise HTTPException(403, "Withdrawal administration is disabled")
    if req.amount > settings.withdrawal_max_amount:
        raise HTTPException(409, "Withdrawal exceeds configured administrative limit")
    if req.risk_score >= settings.withdrawal_high_risk_threshold:
        raise HTTPException(409, "High-risk withdrawal requires manual risk clearance before approval")
    if req.destination and not destination_allowed(req.destination, req.currency, req.network or ""):
        raise HTTPException(409, "Withdrawal destination is not on the approved whitelist")
    async with SessionLocal() as db:
        existing = await db.execute(select(Withdrawal).where(Withdrawal.request_id == req.request_id))
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Withdrawal request already exists")
        w = Withdrawal(
            request_id=req.request_id, account_ref=req.account_ref, amount=req.amount,
            currency=req.currency.upper(), destination_masked=req.destination_masked,
            risk_score=req.risk_score, risk_flags=json_dumps(req.risk_flags),
            required_approvals=2 if settings.withdrawal_dual_approval else 1,
            provider=req.provider or settings.payout_provider,
            destination=req.destination or "",
            destination_tag=req.destination_tag or "",
            network=req.network or "",
            status="PENDING",
        )
        if req.destination:
            w.proposal_digest = proposal_digest(
                request_id=req.request_id, amount=req.amount, currency=req.currency,
                destination=req.destination, tag=req.destination_tag or "",
                network=req.network or "", provider=req.provider or settings.payout_provider,
            )
        db.add(w)
        await db.commit()
        await db.refresh(w)
    await _audit("WITHDRAWAL_CREATED", {"request_id": req.request_id, "amount": req.amount, "currency": req.currency.upper()})
    return {"ok": True, "id": w.id, "status": w.status, "required_approvals": w.required_approvals}


@app.post("/api/admin/withdrawals/{withdrawal_id}/approve")
async def approve_withdrawal(withdrawal_id: int, req: WithdrawalDecision, x_admin_token: str | None = Header(default=None), x_approver_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "TREASURY")
    approver_auth(req.admin_id, x_approver_token, x_admin_token)
    if not settings.withdrawals_enabled:
        raise HTTPException(403, "Withdrawal administration is disabled")
    async with SessionLocal() as db:
        w = (await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id).with_for_update())).scalar_one_or_none()
        if not w:
            raise HTTPException(404, "Withdrawal not found")
        if w.status not in {"PENDING", "PARTIALLY_APPROVED"}:
            raise HTTPException(409, f"Withdrawal is {w.status} and cannot be approved")
        if not w.destination:
            raise HTTPException(409, "Withdrawal destination is required before approval")
        if not destination_allowed(w.destination, w.currency, w.network):
            raise HTTPException(409, "Withdrawal destination is not on the approved whitelist")
        if w.first_approved_by == req.admin_id or w.second_approved_by == req.admin_id:
            raise HTTPException(409, "A different administrator is required for the next approval")
        now = datetime.now(timezone.utc)
        if w.approval_count == 0:
            w.first_approved_by = req.admin_id
            w.first_approved_at = now
            w.approval_count = 1
        elif w.approval_count == 1:
            w.second_approved_by = req.admin_id
            w.second_approved_at = now
            w.approval_count = 2
        else:
            raise HTTPException(409, "Withdrawal already fully approved")
        if w.approval_count >= w.required_approvals:
            w.status = "APPROVED"
        else:
            w.status = "PARTIALLY_APPROVED"
        w.proposal_digest = proposal_digest(
            request_id=w.request_id, amount=w.amount, currency=w.currency,
            destination=w.destination, tag=w.destination_tag, network=w.network,
            provider=w.provider or settings.payout_provider,
        )
        await db.commit()
        result = {"id": w.id, "request_id": w.request_id, "status": w.status, "approval_count": w.approval_count,
                  "required_approvals": w.required_approvals}
    await _audit("WITHDRAWAL_APPROVED", {**result, "admin_id": req.admin_id, "reason": req.reason})
    return {"ok": True, **result, "execution_required": result["status"] == "APPROVED", "message": "Final approval recorded; a release operator must execute the payout." if result["status"] == "APPROVED" else "Second approval required."}


@app.post("/api/admin/withdrawals/{withdrawal_id}/release")
async def release_withdrawal(withdrawal_id: int, req: WithdrawalExecuteRequest, x_admin_token: str | None = Header(default=None), x_release_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    """Execute an approved withdrawal through a separately authenticated release operator."""
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "TREASURY")
    if not verify_release_operator(req.operator_id, x_release_token):
        raise HTTPException(401, "Separate release-operator authentication required")
    if not settings.withdrawals_enabled or not settings.payout_live_enabled:
        raise HTTPException(403, "Payout execution is disabled")
    async with SessionLocal() as db:
        w = (await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id).with_for_update())).scalar_one_or_none()
        if not w:
            raise HTTPException(404, "Withdrawal not found")
        if w.status != "APPROVED":
            raise HTTPException(409, f"Withdrawal is {w.status}; only APPROVED withdrawals can be released")
        if w.risk_score >= settings.withdrawal_review_score and not w.risk_reviewed_by:
            raise HTTPException(409, "High-risk withdrawal requires explicit risk review before release")
        if not w.destination:
            raise HTTPException(409, "Withdrawal has no executable destination")
        if not destination_allowed(w.destination, w.currency, w.network):
            raise HTTPException(409, "Withdrawal destination is not on the approved whitelist")
        provider_name = w.provider or settings.payout_provider
        expected_digest = proposal_digest(request_id=w.request_id, amount=w.amount, currency=w.currency, destination=w.destination, tag=w.destination_tag, network=w.network, provider=provider_name)
        if not w.proposal_digest:
            raise HTTPException(409, "Withdrawal proposal digest is missing; re-approval is required")
        if not hmac.compare_digest(w.proposal_digest, expected_digest):
            raise HTTPException(409, "Withdrawal proposal changed after approval; re-approval required")
        if settings.local_signing_enabled:
            if not verify_local_signature(req.signature or "", expected_digest):
                raise HTTPException(401, "Valid local signing signature is required")
            w.local_signature = req.signature or ""
        try:
            provider = get_payout_provider(provider_name)
        except PayoutError as e:
            raise _safe_http_error(503, e, "Service temporarily unavailable") from e
        idempotency_key = f"withdrawal:{w.request_id}"
        w.status = "SUBMITTING"
        w.execution_operator = req.operator_id
        w.execution_started_at = datetime.now(timezone.utc)
        await db.commit()
        try:
            result = await provider.send(currency=w.currency, amount=w.amount, destination=w.destination,
                                         tag=w.destination_tag, network=w.network,
                                         idempotency_key=idempotency_key,
                                         metadata={"withdrawal_id": w.id, "account_ref": w.account_ref})
        except PayoutUnknown as e:
            async with SessionLocal() as db2:
                w2 = await db2.get(Withdrawal, withdrawal_id)
                w2.status = "UNKNOWN"
                w2.provider = provider_name
                w2.provider_error = str(e)[:1000]
                await db2.commit()
            await _audit("WITHDRAWAL_UNKNOWN", {"id": withdrawal_id, "provider": provider_name, "error": str(e)})
            raise HTTPException(502, "Provider outcome is unknown; reconcile before retrying")
        except PayoutError as e:
            async with SessionLocal() as db2:
                w2 = await db2.get(Withdrawal, withdrawal_id)
                w2.status = "FAILED"
                w2.provider = provider_name
                w2.provider_error = str(e)[:1000]
                await ledger_release_withdrawal(db2, w2.customer_id, w2.amount, reference_id=w2.request_id + ":failed")
                await sync_wallet_from_ledger(db2, w2.customer_id, "USDT")
                await db2.commit()
            await _audit("WITHDRAWAL_FAILED", {"id": withdrawal_id, "provider": provider_name, "error": str(e)})
            raise _safe_http_error(502, e, "Upstream provider request failed") from e
        async with SessionLocal() as db3:
            w3 = (await db3.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id).with_for_update())).scalar_one()
            w3.status = "RELEASED" if result.status == "COMPLETED" else "SUBMITTED"
            w3.provider = result.provider
            w3.provider_id = result.provider_id
            w3.provider_status = result.raw_status or result.status
            w3.provider_error = ""
            if result.status == "COMPLETED":
                await settle_withdrawal(db3, w3.customer_id, w3.amount, reference_id=w3.request_id)
                await sync_wallet_from_ledger(db3, w3.customer_id, "USDT")
            await db3.commit()
        await _audit("WITHDRAWAL_RELEASED", {"id": withdrawal_id, "provider": result.provider,
                                               "provider_id": result.provider_id, "status": result.status})
        return {"ok": True, "id": withdrawal_id, "status": result.status,
                "provider": result.provider, "provider_id": result.provider_id,
                "reconcile_required": settings.payout_require_reconciliation}


@app.post("/api/admin/withdrawals/{withdrawal_id}/risk-review")
async def review_withdrawal_risk(withdrawal_id: int, req: WithdrawalDecision, x_admin_token: str | None = Header(default=None), x_approver_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "RISK_OFFICER")
    approver_auth(req.admin_id, x_approver_token, x_admin_token)
    async with SessionLocal() as db:
        w = (await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id).with_for_update())).scalar_one_or_none()
        if not w:
            raise HTTPException(404, "Withdrawal not found")
        if w.status not in {"PENDING", "PARTIALLY_APPROVED", "APPROVED"}:
            raise HTTPException(409, f"Withdrawal is {w.status} and cannot receive risk review")
        w.risk_reviewed_by = req.admin_id
        w.risk_reviewed_at = datetime.now(timezone.utc)
        await db.commit()
    await _audit("WITHDRAWAL_RISK_REVIEWED", {"id": withdrawal_id, "admin_id": req.admin_id, "risk_score": w.risk_score, "risk_flags": json_loads(w.risk_flags)})
    return {"ok": True, "id": withdrawal_id, "risk_reviewed_by": req.admin_id, "risk_score": w.risk_score, "risk_flags": json_loads(w.risk_flags)}


@app.post("/api/admin/withdrawals/{withdrawal_id}/proposal")
async def withdrawal_proposal(withdrawal_id: int, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "READ_ONLY")
    async with SessionLocal() as db:
        w = await db.get(Withdrawal, withdrawal_id)
        if not w:
            raise HTTPException(404, "Withdrawal not found")
        if w.status != "APPROVED":
            raise HTTPException(409, "Withdrawal must be fully approved before proposal generation")
        if not w.destination:
            raise HTTPException(409, "Withdrawal has no executable destination")
        digest = proposal_digest(request_id=w.request_id, amount=w.amount, currency=w.currency, destination=w.destination, tag=w.destination_tag, network=w.network, provider=w.provider or settings.payout_provider)
        w.proposal_digest = digest
        await db.commit()
        return {"request_id": w.request_id, "digest": digest, "algorithm": "SHA-256 canonical withdrawal proposal", "payload": {"request_id": w.request_id, "amount": w.amount, "currency": w.currency, "destination": w.destination, "tag": w.destination_tag, "network": w.network, "provider": w.provider or settings.payout_provider}}


@app.post("/api/admin/withdrawals/{withdrawal_id}/reconcile")
async def reconcile_withdrawal(withdrawal_id: int, req: WithdrawalReconcileRequest, x_admin_token: str | None = Header(default=None), x_release_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "TREASURY")
    if not verify_release_operator(req.operator_id, x_release_token):
        raise HTTPException(401, "Separate release-operator authentication required")
    async with SessionLocal() as db:
        w = (await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id).with_for_update())).scalar_one_or_none()
        if not w:
            raise HTTPException(404, "Withdrawal not found")
        if w.status not in {"SUBMITTING", "SUBMITTED", "UNKNOWN"}:
            raise HTTPException(409, f"Withdrawal is {w.status} and cannot be reconciled")
        provider = get_payout_provider(w.provider or settings.payout_provider)
        try:
            if w.provider_id:
                result = await provider.status(w.provider_id, currency=w.currency)
            else:
                recover = getattr(provider, "recover", None)
                if recover is None:
                    raise HTTPException(409, "Provider transaction ID is unavailable and this provider does not support idempotency recovery")
                result = await recover(f"withdrawal:{w.request_id}", currency=w.currency)
                if not result.provider_id:
                    raise HTTPException(409, "Provider could not recover a transaction ID; manual provider lookup is required")
                w.provider_id = result.provider_id
        except PayoutUnknown as e:
            raise _safe_http_error(502, e, "Provider reconciliation is currently unresolved") from e
        w.provider_status = result.raw_status or result.status
        w.status = "RELEASED" if result.status == "COMPLETED" else ("FAILED" if result.status == "FAILED" else "SUBMITTED")
        if result.status == "COMPLETED":
            w.reconciled_at = datetime.now(timezone.utc)
            await settle_withdrawal(db, w.customer_id, w.amount, reference_id=w.request_id)
            await sync_wallet_from_ledger(db, w.customer_id, "USDT")
        elif result.status == "FAILED":
            await ledger_release_withdrawal(db, w.customer_id, w.amount, reference_id=w.request_id + ":reconcile-failed")
            await sync_wallet_from_ledger(db, w.customer_id, "USDT")
        await db.commit()
    await _audit("WITHDRAWAL_RECONCILED", {"id": withdrawal_id, "provider_id": w.provider_id, "status": w.status, "operator_id": req.operator_id})
    return {"ok": True, "id": withdrawal_id, "status": w.status, "provider_status": w.provider_status, "provider_id": w.provider_id}


@app.post("/api/admin/withdrawals/{withdrawal_id}/reject")
async def reject_withdrawal(withdrawal_id: int, req: WithdrawalDecision, x_admin_token: str | None = Header(default=None), x_approver_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "TREASURY")
    approver_auth(req.admin_id, x_approver_token, x_admin_token)
    if not settings.withdrawals_enabled:
        raise HTTPException(403, "Withdrawal administration is disabled")
    if not req.reason.strip():
        raise HTTPException(400, "A rejection reason is required")
    async with SessionLocal() as db:
        w = (await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id).with_for_update())).scalar_one_or_none()
        if not w:
            raise HTTPException(404, "Withdrawal not found")
        if w.status not in {"PENDING", "PARTIALLY_APPROVED", "APPROVED"}:
            raise HTTPException(409, f"Withdrawal is {w.status} and cannot be rejected")
        w.status = "REJECTED"
        await ledger_release_withdrawal(db, w.customer_id, w.amount, reference_id=w.request_id + ":rejected")
        await sync_wallet_from_ledger(db, w.customer_id, "USDT")
        w.rejected_by = req.admin_id
        w.rejected_at = datetime.now(timezone.utc)
        w.rejection_reason = req.reason.strip()
        await db.commit()
        result = {"id": w.id, "request_id": w.request_id, "status": w.status}
    await _audit("WITHDRAWAL_REJECTED", {**result, "admin_id": req.admin_id, "reason": req.reason.strip()})
    return {"ok": True, **result}


@app.get("/api/admin/withdrawals/summary")
async def withdrawal_summary(x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "TREASURY")
    async with SessionLocal() as db:
        rows = (await db.execute(select(Withdrawal))).scalars().all()
    pending = [r for r in rows if r.status in {"PENDING", "PARTIALLY_APPROVED"}]
    return {
        "pending_count": len(pending),
        "pending_amount": sum(r.amount for r in pending),
        "approved_count": sum(r.status == "APPROVED" for r in rows),
        "approved_amount": sum(r.amount for r in rows if r.status == "APPROVED"),
        "in_flight_count": sum(r.status in {"SUBMITTING", "SUBMITTED", "UNKNOWN"} for r in rows),
        "rejected_count": sum(r.status == "REJECTED" for r in rows),
        "requires_dual_approval": settings.withdrawal_dual_approval,
    }


@app.get("/api/forex/account")
async def forex_account(x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "READ_ONLY")
    if settings.forex_broker != "oanda":
        raise HTTPException(409, "Forex broker is not configured as OANDA")
    if not settings.oanda_practice:
        raise HTTPException(403, "OANDA live mode is disabled; practice/demo is required")
    if not settings.oanda_account_id or not settings.oanda_api_token:
        raise HTTPException(503, "OANDA demo credentials are not configured")
    from .forex_oanda import OandaBroker, OandaConfig
    broker = OandaBroker(OandaConfig(settings.oanda_account_id, settings.oanda_api_token, True, settings.oanda_timeout_seconds))
    try:
        data = await asyncio.to_thread(broker.account)
        return {"environment": "practice",
                "account_id": data.get("account", {}).get("id"),
                "balance": data.get("account", {}).get("balance"),
                "NAV": data.get("account", {}).get("NAV"),
                "marginAvailable": data.get("account", {}).get("marginAvailable"),
                "unrealizedPL": data.get("account", {}).get("unrealizedPL")}
    finally:
        broker.close()

@app.get("/api/forex/demo/preflight")
async def forex_demo_preflight(instrument: str = "EUR_USD", x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    if not settings.oanda_practice:
        raise HTTPException(403, "OANDA practice mode is required for demo validation")
    if not settings.oanda_account_id or not settings.oanda_api_token:
        raise HTTPException(503, "OANDA practice credentials are not configured")
    from .forex_oanda import OandaBroker, OandaConfig, OandaError
    broker = OandaBroker(OandaConfig(settings.oanda_account_id, settings.oanda_api_token, True, settings.oanda_timeout_seconds))
    try:
        account, quote = await asyncio.gather(
            asyncio.to_thread(broker.account),
            asyncio.to_thread(broker.validate_practice_quote, instrument, settings.oanda_demo_max_quote_age_seconds),
        )
        acct = account.get("account", {})
        return {"ok": True, "environment": "practice", "instrument": instrument,
                "account_id": acct.get("id"), "currency": acct.get("currency"),
                "balance": acct.get("balance"), "NAV": acct.get("NAV"),
                "marginAvailable": acct.get("marginAvailable"), "quote": quote,
                "live_orders_allowed": False, "execution_authority": "demo-only"}
    except OandaError as e:
        raise _safe_http_error(502, e, "Upstream provider request failed") from e
    finally:
        broker.close()

@app.get("/api/forex/demo/price")
async def forex_demo_price(instrument: str = "EUR_USD", x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    if not settings.oanda_practice:
        raise HTTPException(403, "OANDA practice mode is required")
    if not settings.oanda_account_id or not settings.oanda_api_token:
        raise HTTPException(503, "OANDA practice credentials are not configured")
    from .forex_oanda import OandaBroker, OandaConfig, OandaError
    broker = OandaBroker(OandaConfig(settings.oanda_account_id, settings.oanda_api_token, True, settings.oanda_timeout_seconds))
    try:
        return await asyncio.to_thread(broker.validate_practice_quote, instrument, settings.oanda_demo_max_quote_age_seconds)
    except OandaError as e:
        raise _safe_http_error(502, e, "Upstream provider request failed") from e
    finally:
        broker.close()

@app.post("/api/forex/demo/enable")
async def enable_forex_demo(body: LiveEnableRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    if not settings.oanda_practice:
        raise HTTPException(403, "OANDA practice mode is required for demo enablement")
    if body.confirmation != "ENABLE_FOREX_DEMO":
        raise HTTPException(403, "Demo confirmation text did not match")
    if not settings.oanda_account_id or not settings.oanda_api_token:
        raise HTTPException(503, "OANDA practice credentials are not configured")
    from .forex_oanda import OandaBroker, OandaConfig
    broker = OandaBroker(OandaConfig(settings.oanda_account_id, settings.oanda_api_token, True, settings.oanda_timeout_seconds))
    try:
        # Capture the authoritative transaction cursor before closing the client.
        account_snapshot = await asyncio.to_thread(broker.account)
        last_tx = str(account_snapshot.get("lastTransactionID") or account_snapshot.get("account", {}).get("lastTransactionID") or "")
    finally:
        broker.close()
    async with SessionLocal() as db:
        state = await db.get(AppState, 1)
        if not state:
            state = AppState(id=1)
            db.add(state)
        state.forex_demo_enabled = True
        state.mode = "FOREX_DEMO"
        cursor = (await db.execute(select(OandaReconciliationState).where(
            OandaReconciliationState.account_id == settings.oanda_account_id
        ).with_for_update())).scalar_one_or_none()
        if not cursor:
            cursor = OandaReconciliationState(account_id=settings.oanda_account_id)
            db.add(cursor)
        cursor.last_transaction_id = last_tx
        cursor.environment = "practice"
        cursor.status = "READY"
        cursor.last_error = ""
        cursor.last_sync_at = datetime.now(timezone.utc)
        await db.commit()
    return {"enabled": True, "mode": "FOREX_DEMO", "broker": "oanda", "environment": "practice",
            "last_transaction_id": last_tx, "reconciliation": "initialized"}

@app.post("/api/forex/demo/execute")
async def execute_forex_demo(req: ExecuteRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    if req.asset != "forex":
        raise HTTPException(400, "This endpoint only accepts Forex requests")
    if not settings.oanda_practice:
        raise HTTPException(403, "OANDA practice mode is required for Forex demo trading")
    async with SessionLocal() as db:
        state = await db.get(AppState, 1)
        if not state or not state.forex_demo_enabled:
            raise HTTPException(403, "Forex demo trading is not enabled; enable it first")
    if req.quantity > settings.oanda_demo_max_units:
        raise HTTPException(422, f"Demo quantity exceeds configured cap of {settings.oanda_demo_max_units:g} units")
    from .forex_oanda import OandaBroker, OandaConfig, OandaError
    broker = OandaBroker(OandaConfig(settings.oanda_account_id, settings.oanda_api_token, True, settings.oanda_timeout_seconds))
    try:
        quote_check = await asyncio.to_thread(broker.validate_practice_quote, req.symbol, settings.oanda_demo_max_quote_age_seconds)
        live_quote = quote_check["ask"] if req.side == "buy" else quote_check["bid"]
        if req.price > 0:
            reference_slip_bps = abs(live_quote / req.price - 1.0) * 10000.0
            if reference_slip_bps > settings.max_slippage_bps:
                raise HTTPException(409, "Reference price is too far from the current OANDA practice quote")
    except OandaError as e:
        raise _safe_http_error(502, e, "Upstream provider request failed") from e
    finally:
        broker.close()
    try:
        return await execute_signal(req.symbol, req.side, req.quantity, req.price,
                                    {"score": req.score, "long_probability": req.long_probability,
                                     "short_probability": req.short_probability, "flat_probability": req.flat_probability},
                                    "oanda", req.timeframe, req.signal_timestamp or datetime.now(timezone.utc).isoformat(),
                                    False, req.stop_loss_price, req.take_profit_price, req.strategy, "forex", True)
    except RiskBlocked as e:
        raise _safe_http_error(409, e, "Operation could not be completed") from e
    except Exception as e:
        raise _safe_http_error(502, e, "Forex demo execution failed; reconcile OANDA before retrying") from e

@app.post("/api/train")
async def train(req: TrainRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    if str(settings.environment).lower() in {"staging", "production"} and str(settings.process_role).lower() != "worker":
        raise HTTPException(409, "Model training and promotion run only in the Atlas worker process")
    path = model_file(req)
    try:
        df = await asyncio.to_thread(market_data, req)
        result = await asyncio.to_thread(train_model, df, path, req.min_train, req.folds, req.asset)
        await _audit("MODEL_TRAINED", {"model": path, **result})
        return {"ok": True, "model": path, **result}
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


@app.post("/api/backtest")
async def backtest(req: TrainRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    try:
        df = await asyncio.to_thread(market_data, req)
        result = await asyncio.to_thread(ai_walk_forward_backtest, df, req.asset, req.folds, req.min_train, settings.min_signal_score)
        return result
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


@app.post("/api/signal")
async def signal(req: MarketRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    path = model_file(req)
    try:
        df = await asyncio.to_thread(market_data, req)
        result = await asyncio.to_thread(predict_latest, df, path)
        result["exchange"] = req.exchange
        result["symbol"] = req.symbol
        result["timeframe"] = req.timeframe
        return result
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


@app.post("/api/strategy/signal")
async def strategy_signal_api(req: MarketRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    if not settings.strategy_engine_enabled:
        raise HTTPException(403, "Strategy engine is disabled")
    try:
        df = await asyncio.to_thread(market_data, req)
        cfg = StrategyConfig(
            signal_threshold=settings.strategy_signal_threshold,
            target_vol_annual=settings.strategy_target_vol_annual,
            max_leverage=settings.strategy_max_leverage,
            stop_atr=settings.strategy_stop_atr,
            take_profit_atr=settings.strategy_take_profit_atr,
        )
        result = await asyncio.to_thread(strategy_signal, df, cfg, req.asset)
        result.update({"exchange": req.exchange, "symbol": req.symbol, "timeframe": req.timeframe})
        return result
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


@app.post("/api/research/backtest-all")
async def research_backtest_all(req: MarketRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    try:
        df = await asyncio.to_thread(market_data, req)
        cfg = StrategyConfig(
            signal_threshold=settings.strategy_signal_threshold,
            target_vol_annual=settings.strategy_target_vol_annual,
            max_leverage=settings.strategy_max_leverage,
            stop_atr=settings.strategy_stop_atr,
            take_profit_atr=settings.strategy_take_profit_atr,
        )
        result = await asyncio.to_thread(backtest_all_strategies, df, cfg, include_ai=True, asset=req.asset, folds=req.folds, min_train=req.min_train)
        result.update({"exchange": req.exchange, "symbol": req.symbol, "timeframe": req.timeframe})
        await _audit("RESEARCH_BACKTEST_ALL", {"symbol": req.symbol, "asset": req.asset, "strategy_count": result["strategy_count"]})
        return result
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


@app.post("/api/research/paper-signals")
async def research_paper_signals(req: MarketRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    try:
        df = await asyncio.to_thread(market_data, req)
        cfg = StrategyConfig(
            signal_threshold=settings.strategy_signal_threshold,
            target_vol_annual=settings.strategy_target_vol_annual,
            max_leverage=settings.strategy_max_leverage,
            stop_atr=settings.strategy_stop_atr,
            take_profit_atr=settings.strategy_take_profit_atr,
        )
        research = await asyncio.to_thread(backtest_all_strategies, df, cfg, include_ai=True, asset=req.asset, folds=req.folds, min_train=req.min_train)
        candidates = paper_candidates(research)
        names = [x["strategy"] for x in candidates]
        signals = await asyncio.to_thread(live_strategy_signals, df, names, cfg, req.asset)
        return {
            "mode": "PAPER_SHADOW_ONLY",
            "promotion_gate": {"min_sharpe": 0.50, "max_drawdown": -0.25, "min_trades": 20},
            "candidates": names,
            "signals": signals,
            "real_money_execution": False,
            "message": "Strategies must remain in paper/shadow mode until separate production risk and deployment gates are passed.",
        }
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


@app.post("/api/research/review")
async def research_review(req: MarketRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    try:
        df = await asyncio.to_thread(market_data, req)
        cfg = StrategyConfig(
            signal_threshold=settings.strategy_signal_threshold,
            target_vol_annual=settings.strategy_target_vol_annual,
            max_leverage=settings.strategy_max_leverage,
            stop_atr=settings.strategy_stop_atr,
            take_profit_atr=settings.strategy_take_profit_atr,
        )
        research = await asyncio.to_thread(backtest_all_strategies, df, cfg, include_ai=True, asset=req.asset, folds=req.folds, min_train=req.min_train)
        live = await asyncio.to_thread(strategy_signal, df, cfg, req.asset)
        review = await asyncio.to_thread(ai_market_review, research, live)
        review.update({"exchange": req.exchange, "symbol": req.symbol, "timeframe": req.timeframe})
        return review
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


@app.post("/api/research/fx-model")
async def research_fx_model(req: MarketRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    if req.asset != "forex":
        raise HTTPException(400, "FX model requires asset=forex")
    try:
        df = await asyncio.to_thread(market_data, req)
        cfg = FXModelConfig()
        signal = await asyncio.to_thread(fx_model_signal, df, cfg)
        wf = await asyncio.to_thread(fx_walk_forward_score, df, cfg) if len(df) >= 400 else {
            "status": "INSUFFICIENT_HISTORY", "mode": "RESEARCH_ONLY", "execution_authority": False
        }
        return {"symbol": req.symbol, "timeframe": req.timeframe, "exchange": req.exchange,
                "signal": signal, "walk_forward": wf,
                "promotion_status": "PAPER_RESEARCH_ONLY"}
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


@app.post("/api/research/run-daily")
async def research_run_daily(x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    if not settings.daily_research_enabled:
        raise HTTPException(403, "Daily research is disabled")
    result = await run_daily_research()
    await _audit("RESEARCH_DAILY_RUN", {"status": result.get("status"), "symbols": result.get("symbols_requested", [])})
    return result


@app.get("/api/research/runs")
async def research_runs_history(symbol: str | None = None, limit: int = 30, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    """Stored daily research runs with their drift-vs-previous-run comparison, newest first."""
    await auth(x_admin_token, authorization)
    limit = max(1, min(int(limit), 200))
    async with SessionLocal() as db:
        q = select(ResearchRun).order_by(desc(ResearchRun.created_at)).limit(limit)
        if symbol:
            q = select(ResearchRun).where(ResearchRun.symbol == symbol).order_by(desc(ResearchRun.created_at)).limit(limit)
        rows = (await db.execute(q)).scalars().all()
        return [{"id": r.id, "symbol": r.symbol, "run_at": r.run_at.isoformat(), "regime": r.regime_assessment,
                 "top_strategy": r.top_strategy, "sharpe": r.sharpe, "max_drawdown": r.max_drawdown,
                 "total_return": r.total_return, "drift": json.loads(r.regime_drift_json or "{}")} for r in rows]


@app.get("/api/admin/model-experiments")
async def model_experiments_history(model_path: str | None = None, status: str | None = None, limit: int = 50, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    """Adaptive-model retrain history (promotions, rejections, drift alerts), newest first."""
    await auth(x_admin_token, authorization)
    limit = max(1, min(int(limit), 200))
    async with SessionLocal() as db:
        q = select(ModelExperiment)
        if model_path:
            q = q.where(ModelExperiment.model_path == model_path)
        if status:
            q = q.where(ModelExperiment.status == status)
        rows = (await db.execute(q.order_by(desc(ModelExperiment.created_at)).limit(limit))).scalars().all()
        out = []
        for r in rows:
            drift = json.loads(r.feature_drift_json or "{}")
            out.append({"id": r.id, "model_path": r.model_path, "asset": r.asset, "status": r.status,
                        "model_sha256": r.model_sha256, "gate": json.loads(r.gate_json or "{}"),
                        "feature_drift_status": drift.get("status"), "feature_drift_mean_psi": drift.get("mean_psi"),
                        "feature_drift_top_feature": drift.get("max_psi_feature"), "created_at": r.created_at.isoformat()})
        return out


@app.get("/api/admin/learning/episodes")
async def admin_learning_episodes(limit: int = 50, status: str | None = None, replay_status: str | None = None, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    """Operator view of Atlas trade memory and post-trade replay evidence."""
    claims = await admin_claims(authorization, require_aal2=settings.admin_totp_required) if authorization else await auth(x_admin_token, authorization)
    await require_role(claims, "READ_ONLY", "OPERATIONS", "RISK_OFFICER", "ADMINISTRATOR")
    limit = max(1, min(int(limit), 200))
    async with SessionLocal() as db:
        q = select(TradeLearningEpisode)
        if status:
            q = q.where(TradeLearningEpisode.status == status)
        if replay_status:
            q = q.where(TradeLearningEpisode.replay_status == replay_status)
        rows = (await db.execute(q.order_by(desc(TradeLearningEpisode.created_at)).limit(limit))).scalars().all()
        out = []
        for r in rows:
            out.append({
                "id": r.id, "entry_trade_id": r.entry_trade_id, "closing_trade_id": r.closing_trade_id,
                "customer_id": r.customer_id, "bot_id": r.bot_id, "symbol": r.symbol, "exchange": r.exchange,
                "timeframe": r.timeframe, "strategy": r.strategy, "regime": r.regime, "side": r.side,
                "status": r.status, "replay_status": r.replay_status, "replay_version": r.replay_version,
                "entry_price": r.entry_price, "exit_price": r.exit_price, "gross_pnl": r.gross_pnl,
                "total_fees": r.total_fees, "net_pnl": r.net_pnl, "return_bps": r.return_bps,
                "bars_held": r.bars_held, "mfe_bps": r.mfe_bps, "mae_bps": r.mae_bps,
                "market_flow": json.loads(r.market_flow_json or "{}"),
                "memory": json.loads(r.learning_memory_json or "{}"),
                "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
            })
        return out


@app.get("/api/admin/learning/episodes/{episode_id}")
async def admin_learning_episode_detail(episode_id: int, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await admin_claims(authorization, require_aal2=settings.admin_totp_required) if authorization else await auth(x_admin_token, authorization)
    await require_role(claims, "READ_ONLY", "OPERATIONS", "RISK_OFFICER", "ADMINISTRATOR")
    async with SessionLocal() as db:
        ep = await db.get(TradeLearningEpisode, int(episode_id))
        if not ep:
            raise HTTPException(404, "Learning episode not found")
        replays = (await db.execute(select(TradeReplayResult).where(TradeReplayResult.episode_id == ep.id).order_by(TradeReplayResult.strategy))).scalars().all()
        return {
            "id": ep.id, "entry_trade_id": ep.entry_trade_id, "closing_trade_id": ep.closing_trade_id,
            "strategy": ep.strategy, "regime": ep.regime, "symbol": ep.symbol, "timeframe": ep.timeframe,
            "status": ep.status, "replay_status": ep.replay_status, "replay_error": ep.replay_error,
            "gross_pnl": ep.gross_pnl, "total_fees": ep.total_fees, "net_pnl": ep.net_pnl,
            "return_bps": ep.return_bps, "mfe_bps": ep.mfe_bps, "mae_bps": ep.mae_bps,
            "market_flow": json.loads(ep.market_flow_json or "{}"),
            "memory": json.loads(ep.learning_memory_json or "{}"),
            "replays": [{"strategy": x.strategy, "entry_signal": x.entry_signal, "entry_side": x.entry_side,
                         "entry_decision_return_bps": x.entry_decision_return_bps,
                         "policy_window_return_bps": x.policy_window_return_bps, "confidence": x.confidence,
                         "comparison_scope": x.comparison_scope} for x in replays],
        }


@app.post("/api/strategy/backtest-gated")
async def strategy_backtest_gated_api(req: MarketRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    if not settings.strategy_engine_enabled:
        raise HTTPException(403, "Strategy engine is disabled")
    try:
        df = await asyncio.to_thread(market_data, req)
        result = await asyncio.to_thread(gated_entry_exit_backtest, df, EntryExitConfig())
        result.update({"exchange": req.exchange, "symbol": req.symbol, "timeframe": req.timeframe})
        await _audit("RESEARCH_BACKTEST_GATED_ENTRY_EXIT", {"symbol": req.symbol, "asset": req.asset, "trades": result["trades"], "total_return": result["total_return"], "max_drawdown": result["max_drawdown"]})
        return result
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


@app.post("/api/strategy/backtest")
async def strategy_backtest_api(req: MarketRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    if not settings.strategy_engine_enabled:
        raise HTTPException(403, "Strategy engine is disabled")
    try:
        df = await asyncio.to_thread(market_data, req)
        cfg = StrategyConfig(
            signal_threshold=settings.strategy_signal_threshold,
            target_vol_annual=settings.strategy_target_vol_annual,
            max_leverage=settings.strategy_max_leverage,
            stop_atr=settings.strategy_stop_atr,
            take_profit_atr=settings.strategy_take_profit_atr,
        )
        result = await asyncio.to_thread(strategy_backtest, df, cfg, 5.5, 2.0, req.asset)
        result.update({"exchange": req.exchange, "symbol": req.symbol, "timeframe": req.timeframe})
        return result
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


@app.post("/api/paper/step")
async def paper_step(req: MarketRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    path = model_file(req)
    try:
        df = await asyncio.to_thread(market_data, req.model_copy(update={"days": 5}))
        sig = await asyncio.to_thread(predict_latest, df, path)
        price = float(df.close.iloc[-1])
        ts = sig["signal_timestamp"]
        if sig["signal"] == 0:
            return {"mode": "PAPER", "side": "flat", "price": price, **sig}
        side = "buy" if sig["signal"] > 0 else "sell"
        async with SessionLocal() as db:
            s = await db.get(AppState, 1)
            equity = max(0.0, s.equity)
        target_notional = min(equity * settings.risk_per_trade, settings.max_notional_usd)
        qty = target_notional / price
        stop = price * (1 - settings.stop_loss_pct) if side == "buy" else price * (1 + settings.stop_loss_pct)
        tp = price * (1 + settings.take_profit_pct) if side == "buy" else price * (1 - settings.take_profit_pct)
        result = await execute_signal(req.symbol, side, qty, price, sig, req.exchange, req.timeframe, ts,
                                      force_paper=True, stop_loss_price=stop, take_profit_price=tp, asset=req.asset)
        equity_state = await mark_paper_equity({req.symbol: price})
        return {"mode": "PAPER", "side": side, "price": price, "quantity": qty, **sig,
                "execution": result, "equity": equity_state}
    except RiskBlocked as e:
        raise _safe_http_error(409, e, "Operation could not be completed") from e
    except Exception as e:
        raise _safe_http_error(400, e, "Invalid request") from e


@app.post("/api/execute")
async def execute(req: ExecuteRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    signal_timestamp = req.signal_timestamp or datetime.now(timezone.utc).isoformat()
    sig = {"score": req.score, "long_probability": req.long_probability,
           "short_probability": req.short_probability, "flat_probability": req.flat_probability}
    if req.request_id:
        sig["request_id"] = req.request_id
    try:
        return await execute_signal(req.symbol, req.side, req.quantity, req.price, sig, req.exchange,
                                    req.timeframe, signal_timestamp, req.force_paper,
                                    req.stop_loss_price, req.take_profit_price, req.strategy, req.asset, req.demo_forex)
    except RiskBlocked as e:
        raise _safe_http_error(409, e, "Operation could not be completed") from e
    except Exception as e:
        raise _safe_http_error(502, e, "Execution failed; reconcile before retrying") from e


@app.post("/api/reconcile")
async def reconcile_api(req: MarketRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    await auth(x_admin_token, authorization)
    try:
        return await reconcile(req.exchange, req.symbol)
    except Exception as e:
        raise _safe_http_error(502, e, "Upstream provider request failed") from e


@app.post("/api/live/enable")
async def enable_live(body: LiveEnableRequest, x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "RISK_OFFICER")
    if settings.paper_trading or not settings.live_trading_enabled:
        raise HTTPException(403, "Live trading is feature-locked")
    if settings.broker_sandbox:
        raise HTTPException(403, "Broker sandbox mode is enabled; disable sandbox explicitly before live trading")
    if body.confirmation != settings.live_confirmation_text:
        raise HTTPException(403, "Live confirmation text did not match")
    if settings.require_single_worker_for_live and int(os.getenv("WEB_CONCURRENCY", "1")) != 1:
        raise HTTPException(409, "Live trading requires exactly one active execution worker")
    if not settings.exchange_api_key or not settings.exchange_api_secret:
        raise HTTPException(403, "Broker credentials are not configured")
    try:
        from .broker import Broker, BrokerConfig
        b = Broker.get(BrokerConfig(settings.default_exchange, settings.exchange_api_key, settings.exchange_api_secret,
                                    settings.exchange_password, False, settings.default_market_type, settings.exchange_timeout_ms))
        await asyncio.to_thread(b.market_info, settings.default_symbol)
        if settings.require_protective_stop_for_live:
            supported = await asyncio.to_thread(b.feature_value, settings.default_symbol, "stopLoss")
            if not supported:
                raise RuntimeError("Exchange does not advertise unified attached stopLoss support for the default symbol")
    except Exception as e:
        raise _safe_http_error(502, e, "Broker preflight failed") from e
    async with SessionLocal() as db:
        s = await db.get(AppState, 1)
        if s.kill_switch:
            raise HTTPException(409, "Kill switch is active; reset it before enabling live mode")
        s.live_enabled = True
        s.mode = "LIVE"
        await db.commit()
    await _audit("LIVE_ENABLED", {"at": datetime.now(timezone.utc).isoformat()})
    return {"ok": True, "mode": "LIVE"}


@app.post("/api/live/disable")
async def disable_live(x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "RISK_OFFICER")
    async with SessionLocal() as db:
        s = await db.get(AppState, 1)
        s.live_enabled = False
        s.mode = "PAPER"
        await db.commit()
    await _audit("LIVE_DISABLED", {})
    return {"ok": True, "mode": "PAPER"}


@app.post("/api/risk/kill")
async def kill(x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "RISK_OFFICER")
    try:
        return await emergency_stop(settings.default_exchange if settings.exchange_api_key and settings.exchange_api_secret else None)
    except Exception as e:
        raise _safe_http_error(502, e, "Emergency stop state set but broker cancellation failed") from e


@app.post("/api/risk/reset")
async def reset(x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "RISK_OFFICER")
    async with SessionLocal() as db:
        s = await db.get(AppState, 1)
        s.kill_switch = False
        s.live_enabled = False
        s.mode = "PAPER"
        await db.commit()
    await _audit("KILL_SWITCH_RESET", {})
    return {"ok": True, "mode": "PAPER", "live_enabled": False}


async def _audit(event: str, detail: dict, actor_id: str | None = None):
    actor = str(actor_id or _audit_actor.get() or "system")
    async with SessionLocal() as db:
        row = await append_audit(db, event=event, detail=detail, actor_id=actor)
    safe_detail = {k: v for k, v in (detail or {}).items() if k not in {"token", "secret", "api_token", "api_secret", "authorization", "destination"}}
    # The database audit is the transactional record; the external copy is defense-in-depth.
    # A sink outage must not turn a completed money movement into an ambiguous 5xx response
    # that could trigger client retries. Critical sink failures are visible in service logs.
    emit_security_audit(event=event, actor_id=actor, detail=safe_detail, event_hash=row.event_hash)


def json_loads(v):
    import json
    try:
        return json.loads(v or "[]")
    except Exception:
        return []

def json_dumps(v):
    import json
    return json.dumps(v, default=str)


def _safe_http_error(status_code: int, exc: Exception, message: str = "Request could not be completed") -> HTTPException:
    logger.warning("request_operation_failed: status=%s error_type=%s", status_code, type(exc).__name__)
    return HTTPException(status_code, message)

@app.post("/api/admin/models/rollback")
async def admin_model_rollback(req: ModelRollbackRequest, authorization: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "RISK_OFFICER")
    if not settings.model_rollback_enabled:
        raise HTTPException(409, "Model rollback is disabled")
    market = MarketRequest(asset=req.asset, symbol=req.symbol, exchange=req.exchange, timeframe=req.timeframe, days=365)
    path = model_file(market)
    if not rollback_champion(path):
        raise HTTPException(404, "No previous champion artifact is available for rollback")
    await _audit("MODEL_ROLLBACK", {"asset":req.asset,"symbol":req.symbol,"exchange":req.exchange,"timeframe":req.timeframe,"model_path":str(path)})
    return {"ok":True,"status":"ROLLED_BACK","asset":req.asset,"symbol":req.symbol,"model_path":str(path)}


@app.post("/api/research/fx-execution-tca")
async def research_fx_execution_tca(req: dict[str, object], x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "READ_ONLY")
    """Research-only FX transaction-cost analysis; never sends or modifies an order."""
    from .fx_tca import FXExecutionObservation, evaluate_fx_execution
    try:
        obs = FXExecutionObservation(
            provider=str(req.get("provider") or ""),
            symbol=str(req.get("symbol") or "").upper(),
            side=str(req.get("side") or "").lower(),
            quantity=float(req.get("quantity") or 0),
            arrival_mid=float(req.get("arrival_mid") or 0),
            execution_price=float(req.get("execution_price") or 0),
            executed_quantity=float(req.get("executed_quantity") or 0),
            arrival_timestamp_ms=int(req.get("arrival_timestamp_ms") or 0),
            execution_timestamp_ms=int(req.get("execution_timestamp_ms") or 0),
            fee_bps=float(req.get("fee_bps") or 0),
            mid_after_1s=None if req.get("mid_after_1s") is None else float(req.get("mid_after_1s")),
            mid_after_5s=None if req.get("mid_after_5s") is None else float(req.get("mid_after_5s")),
        )
        result = evaluate_fx_execution(obs)
        return {"tca": asdict(result), "execution_authority": False, "mode": "RESEARCH_ONLY"}
    except (TypeError, ValueError) as exc:
        from fastapi import HTTPException
        raise _safe_http_error(400, exc, "Invalid request") from exc

@app.post("/api/research/fx-execution-route")
async def research_fx_execution_route(req: dict[str, object], x_admin_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = await auth(x_admin_token, authorization)
    await require_role(claims, "READ_ONLY")
    """Research-only FX liquidity-provider route comparison; never sends an order."""
    from .fx_execution_router import FXQuote, route_fx_quotes
    try:
        symbol = str(req.get("symbol") or "").upper()
        side = str(req.get("side") or "").lower()
        quantity = float(req.get("quantity") or 0)
        quotes = [FXQuote(**q) for q in (req.get("quotes") or [])]
        plan = route_fx_quotes(
            symbol=symbol,
            side=side,
            quantity=quantity,
            quotes=quotes,
            now_ms=req.get("now_ms"),
            max_quote_age_ms=int(req.get("max_quote_age_ms") or 1500),
            max_latency_ms=float(req.get("max_latency_ms") or 500),
            short_term_vol_bps_per_s=float(req.get("short_term_vol_bps_per_s") or 0),
            max_total_cost_bps=float(req.get("max_total_cost_bps") or 3),
        )
        return {"plan": asdict(plan), "execution_authority": False, "mode": "RESEARCH_ONLY"}
    except (TypeError, ValueError) as exc:
        from fastapi import HTTPException
        raise _safe_http_error(400, exc, "Invalid request") from exc
