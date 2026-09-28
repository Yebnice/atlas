from __future__ import annotations
import asyncio
import hashlib
import json
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError

from .broker import Broker, BrokerConfig
from .customer_binance_execution import build_customer_binance_broker, CustomerBinanceExecutionError
from .customer_oanda import build_customer_oanda_broker
from .risk_governor import evaluate_trade
from .forex_oanda import OandaBroker, OandaConfig
from .config import settings
from .db import (SessionLocal, OandaReconciliationState, AppState, TradingAccount, Trade, Position, AuditLog,
                  Wallet, CustomerOandaAccount, CustomerBinanceAccount, StrategyOutcome, TradeLearningEpisode, OrderCommand,
                  LiveExecutionLease, utcnow, quantize_money)
from .trading_core import PROFILES
from .customer_funds import get_or_create_ledger, reserve_trading, release_trading, sync_wallet_from_ledger, settle_realized_pnl, settle_trading_fee
from .live_execution import assert_live_system_enabled, LiveExecutionBlocked
from .incidents import open_incident
from .ids import make_signal_id, client_order_id
from .audit_chain import record_audit


TERMINAL_STATUSES = {"FILLED", "CANCELED", "REJECTED", "FAILED", "SIMULATED"}



async def audit(event: str, detail: dict, actor_id: str = "system") -> None:
    """Best-effort audit write in its own session; must never break order handling."""
    try:
        await record_audit(event, detail, actor_id=actor_id)
    except Exception:  # noqa: BLE001 - audit sink failure must not turn a fill into an ambiguous error
        import logging
        logging.getLogger(__name__).warning("audit_write_failed event=%s", event, exc_info=True)


class RiskBlocked(RuntimeError):
    pass


_EXECUTION_LOCK = asyncio.Lock()

_EXECUTION_OWNER = os.getenv("K_REVISION", "local") + ":" + uuid.uuid4().hex[:16]


async def _acquire_live_execution_lease(ttl_seconds: int = 30) -> tuple[str, int]:
    now = utcnow()
    async with SessionLocal() as db:
        row = (await db.execute(select(LiveExecutionLease).where(LiveExecutionLease.id == 1).with_for_update())).scalar_one_or_none()
        if row is None:
            row = LiveExecutionLease(id=1, owner_id="", fencing_token=0, expires_at=now)
            db.add(row)
            await db.flush()
        if row.expires_at and row.expires_at > now and row.owner_id and row.owner_id != _EXECUTION_OWNER:
            raise RiskBlocked("Another live execution worker currently holds the submit lease")
        row.owner_id = _EXECUTION_OWNER
        row.fencing_token = int(row.fencing_token or 0) + 1
        row.expires_at = now + __import__("datetime").timedelta(seconds=max(5, int(ttl_seconds)))
        row.updated_at = now
        token = int(row.fencing_token)
        await db.commit()
        return _EXECUTION_OWNER, token


async def _release_live_execution_lease(token: int | None) -> None:
    if token is None:
        return
    now = utcnow()
    async with SessionLocal() as db:
        row = (await db.execute(select(LiveExecutionLease).where(LiveExecutionLease.id == 1).with_for_update())).scalar_one_or_none()
        if row and row.owner_id == _EXECUTION_OWNER and int(row.fencing_token or 0) == int(token):
            row.owner_id = ""
            row.expires_at = now
            row.updated_at = now
            await db.commit()


async def _verify_live_lease(token: int) -> None:
    now = utcnow()
    async with SessionLocal() as db:
        row = await db.get(LiveExecutionLease, 1)
        if not row or row.owner_id != _EXECUTION_OWNER or int(row.fencing_token or 0) != int(token) or row.expires_at <= now:
            raise RiskBlocked("Live execution lease is no longer valid; order submission aborted")


async def _ensure_order_command_in_session(db, trade_id: int, *, customer_id: int | None, exchange: str, symbol: str, side: str, quantity: float, price: float, stop_loss_price: float, take_profit_price: float, client_order_id: str) -> OrderCommand:
    row = (await db.execute(select(OrderCommand).where(OrderCommand.trade_id == trade_id).with_for_update())).scalar_one_or_none()
    if row:
        return row
    row = OrderCommand(
        trade_id=trade_id, customer_id=customer_id, exchange=exchange, symbol=symbol, side=side,
        requested_quantity=quantity, reference_price=price, stop_loss_price=stop_loss_price or 0.0,
        take_profit_price=take_profit_price or 0.0, client_order_id=client_order_id,
        idempotency_key=f"live-trade:{trade_id}:{client_order_id}", status="READY",
    )
    db.add(row)
    await db.flush()
    return row


async def _ensure_order_command(trade_id: int, *, customer_id: int | None, exchange: str, symbol: str, side: str, quantity: float, price: float, stop_loss_price: float, take_profit_price: float, client_order_id: str) -> OrderCommand:
    async with SessionLocal() as db:
        row = await _ensure_order_command_in_session(
            db, trade_id, customer_id=customer_id, exchange=exchange, symbol=symbol, side=side,
            quantity=quantity, price=price, stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price, client_order_id=client_order_id,
        )
        await db.commit()
        await db.refresh(row)
        return row

async def _mark_order_command(command_id: int, *, status: str, token: int | None = None, attempts_increment: bool = False, broker_order_id: str = "", error: str = "") -> None:
    async with SessionLocal() as db:
        row = await db.get(OrderCommand, command_id, with_for_update=True)
        if not row:
            return
        row.status = status
        if token is not None:
            row.fencing_token = int(token)
        if attempts_increment:
            row.attempts = int(row.attempts or 0) + 1
        if broker_order_id:
            row.broker_order_id = broker_order_id[:120]
            row.submitted_at = utcnow()
        row.error = error[:2000]
        row.updated_at = utcnow()
        await db.commit()


async def symbol_lock(symbol: str) -> asyncio.Lock:
    # Risk is portfolio-wide, so execution is intentionally serialized across symbols.
    return _EXECUTION_LOCK


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


async def _ensure_daily_boundary(db, state: AppState):
    today = _today_utc()
    if state.daily_start_date != today:
        state.daily_start_date = today
        state.daily_start_equity = state.equity
        state.updated_at = utcnow()


async def _projected_exposure(db, symbol: str, price: float, quantity: float, side: str, customer_id: int | None = None) -> float:
    q = select(Position)
    if customer_id is not None:
        q = q.where(Position.customer_id == customer_id)
    positions = (await db.execute(q)).scalars().all()
    signed_order = quantity if side == "buy" else -quantity
    total = 0.0
    found = False
    for p in positions:
        if p.symbol == symbol:
            found = True
            post_qty = p.quantity + signed_order
            total += abs(post_qty * price)
        elif p.mark_price > 0:
            total += abs(p.quantity * p.mark_price)
    if not found:
        total += abs(quantity * price)
    return float(total)


async def risk_gate(symbol: str, price: float, quantity: float, live: bool = False,
                    signal_timestamp: str | None = None, side: str = "buy",
                    customer_id: int | None = None, reservation_key: str | None = None,
                    stop_loss_price: float | None = None, take_profit_price: float | None = None,
                    signal: dict | None = None):
    if price <= 0 or quantity <= 0:
        raise RiskBlocked("Invalid price or quantity")
    async with SessionLocal() as db:
        platform = await db.execute(select(AppState).where(AppState.id == 1).with_for_update())
        s = platform.scalar_one_or_none()
        if not s:
            raise RiskBlocked("Risk state unavailable")
        await _ensure_daily_boundary(db, s)
        if s.kill_switch:
            raise RiskBlocked("Kill switch is active")

        account = None
        account_reduce_only = False
        if customer_id is not None:
            account = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == customer_id).with_for_update())).scalar_one_or_none()
            if not account:
                raise RiskBlocked("Customer trading account is not active")
            # Determine -- before the account-status gate -- whether this specific order
            # can only reduce/close existing exposure on this symbol (i.e. its quantity
            # does not exceed the opposing position, so it cannot flip into a larger new
            # position). A HALTED account (drawdown/daily-loss circuit breaker) must still
            # allow this kind of order through: otherwise the discipline system, whose
            # purpose is to protect the customer, instead traps them in the exact losing
            # position it was designed to get them out of, with no way to exit via the API.
            qpos_symbol = select(Position).where(Position.customer_id == customer_id, Position.symbol == symbol, Position.quantity != 0)
            positions_for_symbol = (await db.execute(qpos_symbol)).scalars().all()
            signed = quantity if side == "buy" else -quantity
            opposing_qty = sum(abs(p.quantity) for p in positions_for_symbol if (p.quantity > 0 > signed) or (p.quantity < 0 < signed))
            account_reduce_only = opposing_qty > 0 and quantity <= opposing_qty + 1e-9
            if account.status != "ACTIVE" and not (account.status == "HALTED" and account_reduce_only):
                raise RiskBlocked("Customer trading account is not active")
            if settings.customer_cash_only_trading:
                ledger = await get_or_create_ledger(db, customer_id, "USDT")
                # Loose (direction-only, not magnitude-capped) reducing check: only used to
                # decide whether new cash needs to be reserved for this order, matching the
                # existing behavior. account_reduce_only above is the stricter, magnitude-capped
                # check used only to decide whether a HALTED account may still place this order.
                reducing = any((p.quantity > 0 > signed) or (p.quantity < 0 < signed) for p in positions_for_symbol)
                required_cash = 0.0 if reducing else price * quantity
                if float(ledger.available) + 1e-9 < required_cash:
                    raise RiskBlocked("Order exceeds the customer's available funded USDT balance")
            today = _today_utc()
            if account.daily_start_date != today:
                account.daily_start_date = today
                account.daily_start_equity = account.equity
            equity = max(0.0, account.equity)
            peak = account.peak_equity or equity
            daily_start = account.daily_start_equity or equity
        else:
            equity = max(0.0, s.equity)
            peak = s.peak_equity or equity
            daily_start = s.daily_start_equity or equity

        # Determine whether this order increases exposure. Discipline controls should
        # not block an order that only reduces an existing position.
        qpos = select(Position).where(Position.symbol == symbol, Position.quantity != 0)
        if customer_id is not None:
            qpos = qpos.where(Position.customer_id == customer_id)
        existing_positions = (await db.execute(qpos)).scalars().all()
        signed = quantity if side == "buy" else -quantity
        reducing = any((p.quantity > 0 > signed) or (p.quantity < 0 < signed) for p in existing_positions)

        if settings.discipline_enabled and not reducing:
            now = datetime.now(timezone.utc)
            day_start_utc = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)
            active_statuses = {"PENDING", "NEW", "SUBMITTED", "OPEN", "PARTIAL", "FILLED", "SIMULATED"}
            qtrades = select(Trade).where(Trade.created_at >= day_start_utc, Trade.status.in_(active_statuses))
            if customer_id is not None:
                qtrades = qtrades.where(Trade.customer_id == customer_id)
            todays_entries = (await db.execute(select(func.count()).select_from(qtrades.subquery()))).scalar_one()
            if int(todays_entries) >= settings.discipline_max_entries_per_day:
                raise RiskBlocked("Trading-discipline daily entry limit reached")

            qlast = select(Trade.created_at).where(Trade.created_at >= day_start_utc, Trade.status.in_(active_statuses)).order_by(Trade.created_at.desc()).limit(1)
            if customer_id is not None:
                qlast = qlast.where(Trade.customer_id == customer_id)
            last_entry = (await db.execute(qlast)).scalar_one_or_none()
            if last_entry is not None:
                if last_entry.tzinfo is None:
                    last_entry = last_entry.replace(tzinfo=timezone.utc)
                elapsed = (now - last_entry).total_seconds()
                if elapsed < settings.discipline_entry_cooldown_seconds:
                    raise RiskBlocked("Trading-discipline entry cooldown is active")

        dd = 1 - (equity / peak) if peak else 0.0
        daily_loss = 1 - (equity / daily_start) if daily_start else 0.0
        if dd >= settings.max_drawdown or daily_loss >= settings.daily_loss_limit:
            already_halted_exit = account is not None and account.status == "HALTED" and account_reduce_only
            if account is not None:
                account.status = "HALTED"
            else:
                s.kill_switch = True
                s.live_enabled = False
                s.mode = "HALTED"
            if not already_halted_exit:
                await db.commit()
                raise RiskBlocked("Customer/account risk loss limit reached" if account is not None else "Maximum drawdown or daily loss limit reached")
            # already_halted_exit: this order only closes/reduces an existing position on an
            # account already marked HALTED by a prior breach -- let it through so the customer
            # can exit, rather than re-raising and trapping them in the position again.

        notional = price * quantity
        if settings.discipline_enabled and settings.discipline_enforce_risk_per_trade and not reducing:
            if stop_loss_price is None or stop_loss_price <= 0:
                raise RiskBlocked("Trading discipline requires a protective stop for new exposure")
            risk_cash = abs(price - float(stop_loss_price)) * quantity
            allowed_risk = equity * settings.risk_per_trade * (1.0 + settings.discipline_risk_tolerance)
            if not (risk_cash <= allowed_risk + 1e-9):
                raise RiskBlocked("Per-trade risk exceeds the configured discipline limit")
        max_account_notional = equity * settings.max_leverage
        if notional > min(settings.max_notional_usd, settings.max_position_notional_usd, max_account_notional):
            raise RiskBlocked("Order notional exceeds configured account/position limit")
        projected_exposure = await _projected_exposure(db, symbol, price, quantity, side, customer_id)
        if projected_exposure > min(settings.max_total_exposure_usd, max_account_notional):
            raise RiskBlocked("Total portfolio exposure limit exceeded")
        q = select(Position).where(Position.quantity != 0)
        if customer_id is not None:
            q = q.where(Position.customer_id == customer_id)
        open_positions = (await db.execute(q)).scalars().all()
        if symbol not in {p.symbol for p in open_positions} and len(open_positions) >= settings.max_open_positions:
            raise RiskBlocked("Maximum open position count reached")
        if live and signal_timestamp:
            try:
                ts = datetime.fromisoformat(signal_timestamp.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                if age > settings.max_signal_age_seconds:
                    raise RiskBlocked("Signal is stale")
                if age < -60:
                    raise RiskBlocked("Signal timestamp is too far in the future")
            except ValueError:
                raise RiskBlocked("Invalid signal timestamp")
        await db.commit()


async def _get_state_locked(db) -> AppState:
    result = await db.execute(select(AppState).where(AppState.id == 1).with_for_update())
    s = result.scalar_one_or_none()
    if not s:
        raise RiskBlocked("Risk state unavailable")
    await _ensure_daily_boundary(db, s)
    return s


async def _create_trade(symbol: str, timeframe: str, side: str, quantity: float, price: float,
                        exchange: str, mode: str, signal: dict[str, Any], signal_id: str,
                        cid: str, stop_loss_price: float = 0.0, take_profit_price: float = 0.0,
                        customer_id: int | None = None, trading_account_id: int | None = None):
    async with SessionLocal() as db:
        try:
            trade = Trade(
                customer_id=customer_id, trading_account_id=trading_account_id,
                signal_id=signal_id, client_order_id=cid, symbol=symbol, timeframe=timeframe,
                exchange=exchange, side=side, quantity=quantity, requested_quantity=quantity,
                remaining_quantity=quantity, requested_price=price, mode=mode, status="PENDING",
                reason=json.dumps(signal, default=str), stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
            )
            db.add(trade)
            await db.flush()
            try:
                strategy = str(signal.get("strategy") or "unknown")
                regime = str(signal.get("regime") or "UNKNOWN")
                bot_id = int(signal.get("bot_id")) if str(signal.get("bot_id", "")).isdigit() else None
                db.add(TradeLearningEpisode(
                    entry_trade_id=trade.id, customer_id=customer_id, bot_id=bot_id,
                    asset=str(signal.get("asset") or "crypto"), exchange=exchange, symbol=symbol,
                    timeframe=timeframe, side=side, strategy=strategy, regime=regime,
                    model_version=str(signal.get("model_version") or ""),
                    decision_snapshot_json=json.dumps(signal, default=str),
                ))
            except Exception:
                # Trading execution must not fail because post-trade learning memory
                # is unavailable. The immutable Trade remains the source of truth.
                pass
            await db.commit()
            await db.refresh(trade)
            return trade.id, True
        except IntegrityError:
            await db.rollback()
            result = await db.execute(select(Trade).where(Trade.client_order_id == cid))
            existing = result.scalar_one()
            return existing.id, False


async def _apply_fill_to_position(db, trade: Trade, new_filled: float, fill_price: float):
    delta = max(0.0, new_filled - trade.filled_quantity)
    if delta <= 0 or fill_price <= 0:
        trade.filled_quantity = new_filled
        trade.remaining_quantity = max(0.0, trade.requested_quantity - new_filled)
        return 0.0
    signed = delta if trade.side == "buy" else -delta
    trade_context = {}
    try:
        trade_context = json.loads(trade.reason or "{}")
    except Exception:
        trade_context = {}
    position = (await db.execute(select(Position).where(Position.symbol == trade.symbol, Position.exchange == trade.exchange, Position.customer_id == trade.customer_id).with_for_update())).scalar_one_or_none()
    realized = 0.0
    realized_strategy = str(getattr(position, "strategy", "") or trade_context.get("strategy") or "unknown") if position else str(trade_context.get("strategy") or "unknown")
    realized_regime = str(getattr(position, "entry_regime", "UNKNOWN") or trade_context.get("regime") or "UNKNOWN") if position else str(trade_context.get("regime") or "UNKNOWN")
    entry_trade_id = getattr(position, "entry_trade_id", None) if position else trade.id
    if not position:
        position = Position(customer_id=trade.customer_id, trading_account_id=trade.trading_account_id, exchange=trade.exchange, symbol=trade.symbol, quantity=signed,
                            average_entry_price=fill_price, mark_price=fill_price,
                            strategy=str(trade_context.get("strategy") or "unknown"),
                            entry_regime=str(trade_context.get("regime") or "UNKNOWN"),
                            entry_trade_id=trade.id,
                            reserved_capital=(delta * fill_price if settings.customer_cash_only_trading and trade.customer_id is not None else 0.0))
        db.add(position)
    else:
        old_qty = position.quantity
        if old_qty == 0 or (old_qty > 0 and signed > 0) or (old_qty < 0 and signed < 0):
            total_abs = abs(old_qty) + abs(signed)
            position.average_entry_price = (
                abs(old_qty) * position.average_entry_price + abs(signed) * fill_price
            ) / total_abs
            position.quantity = old_qty + signed
            if settings.customer_cash_only_trading and trade.customer_id is not None:
                position.reserved_capital += delta * fill_price
        else:
            closing = min(abs(old_qty), abs(signed))
            direction = 1 if old_qty > 0 else -1
            realized = closing * (fill_price - position.average_entry_price) * direction
            position.quantity = old_qty + signed
            if settings.customer_cash_only_trading and trade.customer_id is not None and abs(old_qty) > 0:
                released = position.reserved_capital * (closing / abs(old_qty))
                position.reserved_capital = max(0.0, position.reserved_capital - released)
                if released > 0:
                    await release_trading(db, trade.customer_id, released, reference_id=f"trade:{trade.id}:close:{int(new_filled * 1000000)}")
                    account_locked = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == trade.customer_id).with_for_update())).scalar_one_or_none()
                    if account_locked:
                        account_locked.reserved_margin = max(0.0, account_locked.reserved_margin - released)
            if position.quantity != 0 and (old_qty * position.quantity < 0):
                position.strategy = str(trade_context.get("strategy") or "unknown")
                position.entry_regime = str(trade_context.get("regime") or "UNKNOWN")
                position.entry_trade_id = trade.id
                position.average_entry_price = fill_price
                if settings.customer_cash_only_trading and trade.customer_id is not None:
                    position.reserved_capital += abs(position.quantity) * fill_price
                    await reserve_trading(db, trade.customer_id, abs(position.quantity) * fill_price,
                                          reference_id=f"trade:{trade.id}:flip:{int(new_filled * 1000000)}")
                    account_locked = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == trade.customer_id).with_for_update())).scalar_one_or_none()
                    if account_locked:
                        account_locked.reserved_margin += abs(position.quantity) * fill_price
        # Maintain the trade-learning episode anchored to the position-opening trade.
        episode_trade_id = int(entry_trade_id or trade.id)
        episode = (await db.execute(
            select(TradeLearningEpisode).where(TradeLearningEpisode.entry_trade_id == episode_trade_id).with_for_update()
        )).scalar_one_or_none()
        position_flipped = bool(old_qty if 'old_qty' in locals() else 0) and bool(position.quantity) and (old_qty * position.quantity < 0 if 'old_qty' in locals() else False)
        if position_flipped and episode is not None:
            # The previous position lifecycle has ended even though a new opposite
            # position was opened by the same order. Close the old episode before
            # initializing the new one below.
            episode.status = "COMPLETED"
            episode.closing_trade_id = trade.id
            episode.exit_price = float(fill_price)
            episode.exit_at = utcnow()

        if position_flipped:
            new_episode = (await db.execute(
                select(TradeLearningEpisode).where(TradeLearningEpisode.entry_trade_id == trade.id).with_for_update()
            )).scalar_one_or_none()
            if new_episode is not None:
                episode = new_episode
                episode_trade_id = trade.id
                if episode.entry_price <= 0:
                    episode.entry_price = float(fill_price)
                if episode.entry_quantity <= 0:
                    episode.entry_quantity = abs(float(position.quantity))
                episode.status = "OPEN"
                episode.exit_at = None
                episode.closing_trade_id = None
        if episode is not None:
            if episode.entry_price <= 0:
                episode.entry_price = float(fill_price)
            # For a position-opening fill, accumulate the actual filled quantity.
            if (episode.status == "OPEN" or episode.entry_quantity <= 0) and signed * (1 if episode.side == "buy" else -1) > 0:
                prior_qty = float(episode.entry_quantity or 0.0)
                new_qty = prior_qty + abs(float(delta))
                if prior_qty > 0 and float(episode.entry_price) > 0:
                    episode.entry_price = ((prior_qty * float(episode.entry_price)) + (abs(float(delta)) * float(fill_price))) / new_qty
                else:
                    episode.entry_price = float(fill_price)
                episode.entry_quantity = new_qty
            if realized != 0.0:
                episode.gross_pnl = quantize_money(float(episode.gross_pnl or 0.0) + float(realized))
                episode.exit_price = float(fill_price)
                episode.closing_trade_id = trade.id
                episode.exit_at = utcnow()
                # Fees are recomputed from the immutable entry and closing trades so
                # cumulative broker fee fields cannot be double-counted.
                entry_trade = await db.get(Trade, episode_trade_id)
                close_rows = (await db.execute(
                    select(Trade).where(Trade.id.in_(
                        select(StrategyOutcome.closing_trade_id).where(
                            StrategyOutcome.trade_id == episode_trade_id,
                            StrategyOutcome.closing_trade_id.is_not(None),
                        )
                    ))
                )).scalars().all()
                total_fees = float(entry_trade.fee or 0.0) if entry_trade else 0.0
                total_fees += sum(float(x.fee or 0.0) for x in close_rows if x.id != trade.id)
                total_fees += float(trade.fee or 0.0)
                episode.total_fees = total_fees
                episode.net_pnl = quantize_money(float(episode.gross_pnl or 0.0) - total_fees)
                notional = abs(float(episode.entry_quantity or 0.0) * float(episode.entry_price or 0.0))
                episode.return_bps = float(episode.net_pnl / notional * 10000.0) if notional > 0 else 0.0
            if abs(float(position.quantity or 0.0)) < 1e-12:
                episode.status = "COMPLETED"
                episode.exit_price = float(fill_price)
                episode.exit_at = utcnow()
            elif episode.entry_quantity > 0:
                episode.status = "OPEN"
            episode.updated_at = utcnow()

        position.mark_price = fill_price
        # Bound float-drift on this running total across a position's lifetime. This doesn't
        # affect fund safety on its own -- settle_realized_pnl() below converts `realized`
        # through Decimal independently on every call before it touches the customer ledger --
        # but an unbounded position.realized_pnl is still a reporting-accuracy issue over a
        # long-lived position with many partial fills.
        position.realized_pnl = quantize_money(position.realized_pnl + realized)
        if realized and trade.customer_id is not None:
            await settle_realized_pnl(db, customer_id=trade.customer_id, amount=realized, reference_id=f"trade:{trade.id}:realized:{int(new_filled * 1000000)}")
        if realized != 0.0:
            # Store observed outcome against the strategy that opened the position.
            # This avoids attributing a close to the strategy of the closing order.
            attribution_trade_id = int(entry_trade_id or trade.id)
            existing_count = await db.execute(select(func.count(StrategyOutcome.id)).where(StrategyOutcome.trade_id == attribution_trade_id))
            sequence = int(existing_count.scalar_one() or 0) + 1
            notional = abs(float(delta * fill_price))
            return_bps = float(realized / notional * 10000.0) if notional > 0 else 0.0
            closing_fee = float(trade.fee or 0.0)
            entry_row = await db.get(Trade, attribution_trade_id)
            entry_fee = float(entry_row.fee or 0.0) if entry_row else 0.0
            episode_entry_qty = float(episode.entry_quantity or 0.0) if 'episode' in locals() and episode is not None else 0.0
            allocated_entry_fee = entry_fee * (float(closing) / episode_entry_qty) if episode_entry_qty > 0 else 0.0
            net_pnl = float(realized - closing_fee - allocated_entry_fee)
            net_return_bps = float(net_pnl / notional * 10000.0) if notional > 0 else 0.0
            db.add(StrategyOutcome(
                trade_id=attribution_trade_id, closing_trade_id=trade.id, customer_id=trade.customer_id,
                bot_id=int(trade_context.get("bot_id")) if str(trade_context.get("bot_id", "")).isdigit() else None,
                strategy=realized_strategy, regime=realized_regime, asset=str(trade_context.get("asset") or "crypto"),
                symbol=trade.symbol, timeframe=trade.timeframe, side=trade.side,
                realized_pnl=realized, fee=float(trade.fee or 0.0), return_bps=return_bps,
                net_pnl=net_pnl, net_return_bps=net_return_bps,
                mode=trade.mode, sequence=sequence, model_version=str(trade_context.get("model_version") or ""),
                metadata_json=json.dumps({"entry_trade_id": attribution_trade_id, "closing_trade_id": trade.id, "fill_price": fill_price, "entry_fee": entry_fee, "allocated_entry_fee": allocated_entry_fee, "net_pnl": net_pnl}, default=str),
            ))
        position.unrealized_pnl = position.quantity * (position.mark_price - position.average_entry_price) if position.quantity else 0.0
        position.updated_at = utcnow()
    trade.filled_quantity = new_filled
    trade.remaining_quantity = max(0.0, trade.requested_quantity - new_filled)
    trade.average_fill_price = fill_price
    trade.notional = new_filled * fill_price
    return realized


async def _release_unneeded_order_reserve(db, trade: Trade) -> float:
    """Release only capital no longer backing a terminal customer order.

    The amount originally reserved is persisted on the Trade. This avoids reconstructing
    reserve state from requested price and prevents partial fills from losing collateral.
    A small slippage buffer is reserved before submission; if a terminal fill still costs
    more than the stored reserve, the function attempts to top up the reserve from the
    customer's available balance and opens a critical incident if that cannot be done.
    """
    if trade.customer_id is None or not settings.customer_cash_only_trading:
        return 0.0
    reserved = max(0.0, float(trade.reserved_cash or 0.0))
    if reserved <= 0:
        legacy = max(0.0, float(trade.requested_quantity or 0.0) * float(trade.requested_price or 0.0))
        reserved = legacy
    filled_cost = max(0.0, float(trade.filled_quantity or 0.0) * float(trade.average_fill_price or trade.requested_price or 0.0))
    if filled_cost > reserved + 1e-12:
        deficit = filled_cost - reserved
        try:
            await reserve_trading(db, trade.customer_id, deficit,
                                  reference_id=f"trade:{trade.id}:reserve-deficit:{int(round(float(trade.filled_quantity or 0.0) * 1000000))}")
            reserved += deficit
            trade.reserved_cash = reserved
            account_locked = (await db.execute(select(TradingAccount).where(
                TradingAccount.customer_id == trade.customer_id
            ).with_for_update())).scalar_one_or_none()
            if account_locked:
                account_locked.reserved_margin += deficit
            await sync_wallet_from_ledger(db, trade.customer_id, "USDT")
        except ValueError as exc:
            trade.error = (str(trade.error or "") + " | RESERVE_DEFICIT: " + str(exc))[:4000]
            await open_incident(
                key=f"TRADE_RESERVE_DEFICIT:{trade.id}",
                severity="CRITICAL",
                category="LEDGER_RECONCILIATION",
                summary="Filled trade exceeded reserved customer cash",
                detail={"trade_id": trade.id, "customer_id": trade.customer_id, "reserved_cash": reserved, "filled_cost": filled_cost, "deficit": deficit, "error": str(exc)},
                customer_id=trade.customer_id,
            )
            return 0.0
    release = max(0.0, reserved - filled_cost)
    if release <= 0:
        return 0.0
    await release_trading(db, trade.customer_id, release, reference_id=f"trade:{trade.id}:order-reserve-release")
    account_locked = (await db.execute(select(TradingAccount).where(
        TradingAccount.customer_id == trade.customer_id
    ).with_for_update())).scalar_one_or_none()
    if account_locked:
        account_locked.reserved_margin = max(0.0, account_locked.reserved_margin - release)
    trade.reserved_cash = filled_cost
    await sync_wallet_from_ledger(db, trade.customer_id, "USDT")
    return release


async def mark_paper_equity(mark_prices: dict[str, float], customer_id: int | None = None):
    async with SessionLocal() as db:
        if customer_id is None:
            state = await _get_state_locked(db)
            q = select(Position).where(Position.customer_id.is_(None))
        else:
            account = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == customer_id).with_for_update())).scalar_one_or_none()
            if not account:
                raise RiskBlocked("Customer trading account is unavailable")
            today = _today_utc()
            if account.daily_start_date != today:
                account.daily_start_date = today
                account.daily_start_equity = account.equity
            q = select(Position).where(Position.customer_id == customer_id)
        realized = 0.0
        unrealized = 0.0
        positions = (await db.execute(q)).scalars().all()
        for p in positions:
            if p.symbol in mark_prices and mark_prices[p.symbol] > 0:
                p.mark_price = mark_prices[p.symbol]
            p.unrealized_pnl = p.quantity * (p.mark_price - p.average_entry_price) if p.quantity and p.mark_price else 0.0
            realized += p.realized_pnl
            unrealized += p.unrealized_pnl
        if customer_id is None:
            state.realized_pnl = realized
            state.unrealized_pnl = unrealized
            state.equity = max(0.0, state.cash_equity + realized + unrealized)
            state.peak_equity = max(state.peak_equity, state.equity)
            await _ensure_daily_boundary(db, state)
            result = {"equity": state.equity, "realized_pnl": realized, "unrealized_pnl": unrealized,
                      "drawdown": (state.equity / state.peak_equity - 1 if state.peak_equity else 0.0)}
        else:
            account.realized_pnl = realized
            account.unrealized_pnl = unrealized
            account.equity = max(0.0, account.cash_equity + realized + unrealized)
            account.peak_equity = max(account.peak_equity, account.equity)
            result = {"equity": account.equity, "realized_pnl": realized, "unrealized_pnl": unrealized,
                      "drawdown": (account.equity / account.peak_equity - 1 if account.peak_equity else 0.0)}
        await db.commit()
        return result


async def execute_signal(symbol: str, side: str, quantity: float, price: float, signal: dict[str, Any],
                         exchange: str, timeframe: str, signal_timestamp: str, force_paper: bool = False,
                         stop_loss_price: float | None = None, take_profit_price: float | None = None,
                         strategy: str = "lightgbm-wf-v1", asset: str = "crypto", demo_forex: bool = False,
                         customer_id: int | None = None):
    signal = dict(signal or {})
    signal.setdefault("strategy", strategy)
    signal.setdefault("asset", asset)
    if side not in {"buy", "sell"}:
        raise RiskBlocked("Invalid order side")
    lock = await symbol_lock(symbol)
    async with lock:
        async with SessionLocal() as db:
            s = await _get_state_locked(db)
            account = None
            if customer_id is not None:
                account = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == customer_id).with_for_update())).scalar_one_or_none()
                # HALTED accounts are let through this early gate on purpose: risk_gate() (called
                # unconditionally below) is the authority that blocks every HALTED order except a
                # capped reduce-only exit, so a customer is never trapped in the position that
                # tripped the circuit breaker. Any other non-ACTIVE status is still rejected here.
                if not account or account.status not in {"ACTIVE", "HALTED"}:
                    raise RiskBlocked("Customer trading account is not active")
            if s.kill_switch:
                raise RiskBlocked("Kill switch is active")
            crypto_live = bool(s.live_enabled and settings.live_trading_enabled and not settings.paper_trading and not force_paper and asset == "crypto")
            forex_demo = bool(asset in {"forex", "commodity"} and demo_forex and s.forex_demo_enabled and settings.oanda_practice and not force_paper)
            # OANDA is permanently demo/practice-only in AtlasRisk. Never derive live authority
            # from a configuration flag, and never allow a customer OANDA credential to become
            # a live execution path.
            forex_live = False
            if asset in {"forex", "commodity"} and not forex_demo and not force_paper:
                raise RiskBlocked("OANDA is demo/backtesting-only in AtlasRisk; live Forex/commodity execution is disabled")
            live = crypto_live or forex_demo
            if crypto_live and settings.broker_sandbox:
                raise RiskBlocked("Live crypto trading cannot run while broker sandbox mode is enabled")
            if asset in {"forex", "commodity"} and demo_forex and not forex_demo:
                raise RiskBlocked("Forex demo mode is not enabled or OANDA practice mode is not configured")
            if asset in {"forex", "commodity"} and forex_live and settings.oanda_practice:
                raise RiskBlocked("OANDA practice mode is enabled; live Forex is locked")
            mode = "FOREX_DEMO" if forex_demo else ("LIVE" if live else "PAPER")
            equity = account.equity if account is not None else s.equity
            trading_account_id = account.id if account is not None else None

        base_scope = f"{strategy}:customer:{customer_id if customer_id is not None else 'platform'}"
        execution_instance = str(signal.get("request_id") or signal.get("idempotency_key") or signal.get("bot_id") or signal.get("executor_id") or "").strip()
        signal_scope = f"{base_scope}:{execution_instance}" if execution_instance else base_scope
        signal_id = make_signal_id(exchange, symbol, timeframe, signal_timestamp, side, signal_scope)
        cid = client_order_id(signal_id)

        # In live mode, the exchange quote is authoritative. Never trust a client-supplied price for risk sizing.
        broker = None
        quote = price
        if live:
            # Customer live trading requires a verified isolated exchange/subaccount adapter.
            # Customer crypto execution must resolve only the customer's verified venue mapping.
            # Never fall back to platform-wide exchange credentials for a customer order.
            if customer_id is not None and asset != "forex":
                if exchange.lower() != "binance":
                    raise RiskBlocked("Customer live crypto trading requires a verified isolated exchange/subaccount adapter")
                async with SessionLocal() as credential_db:
                    from .db import CustomerBinanceAccount
                    customer_binance = (await credential_db.execute(
                        select(CustomerBinanceAccount).where(
                            CustomerBinanceAccount.customer_id == customer_id
                        )
                    )).scalar_one_or_none()
                try:
                    broker = build_customer_binance_broker(
                        customer_binance,
                        timeout_ms=settings.exchange_timeout_ms,
                        sandbox=settings.broker_sandbox,
                    )
                except CustomerBinanceExecutionError as exc:
                    raise RiskBlocked(str(exc)) from exc
            elif asset in {"forex", "commodity"}:
                # Defensive assertion: forex/commodity reaches the broker only through the
                # explicit demo path above. OANDA has no live execution authority in AtlasRisk.
                raise RiskBlocked("OANDA live execution is disabled; use the demo/backtesting path")
            else:
                broker = Broker.get(BrokerConfig(
                    exchange_id=exchange, api_key=settings.exchange_api_key,
                    api_secret=settings.exchange_api_secret, password=settings.exchange_password,
                    sandbox=settings.broker_sandbox, market_type=settings.default_market_type,
                    timeout_ms=settings.exchange_timeout_ms,
                ))
            ticker = await asyncio.to_thread(broker.ticker, symbol)
            quote = float(ticker.get("ask") if side == "buy" and ticker.get("ask") else
                          ticker.get("bid") if side == "sell" and ticker.get("bid") else ticker.get("last") or 0)
            if quote <= 0:
                raise RiskBlocked("Broker returned no usable market price")
            if price > 0:
                slip = abs(quote / price - 1) * 10_000
                if slip > settings.max_slippage_bps:
                    raise RiskBlocked("Requested reference price is too far from live market")

        if live and settings.require_protective_stop_for_live:
            if not stop_loss_price:
                raise RiskBlocked("Live orders require an explicit protective stop price")
            stop_loss_price = float(stop_loss_price)
            if (side == "buy" and stop_loss_price >= quote) or (side == "sell" and stop_loss_price <= quote):
                raise RiskBlocked("Protective stop is on the wrong side of the market")
            if take_profit_price is not None:
                tp = float(take_profit_price)
                if (side == "buy" and tp <= quote) or (side == "sell" and tp >= quote):
                    raise RiskBlocked("Take-profit is on the wrong side of the market")
            if broker is not None and not await asyncio.to_thread(broker.supports_feature, symbol, "stopLoss"):
                raise RiskBlocked("Exchange does not support the required attached stopLoss feature for this symbol")
            if take_profit_price is not None and not await asyncio.to_thread(broker.supports_feature, symbol, "takeProfit"):
                raise RiskBlocked("Exchange does not support the requested attached takeProfit feature for this symbol")

        if live and asset in {"forex", "commodity"} and broker is not None:
            try:
                symbol = symbol.strip().upper().replace("/", "_").replace("-", "_")
                quantity = await asyncio.to_thread(broker.validate_order_units, symbol, quantity)
                info = await asyncio.to_thread(broker.market_info, symbol)
                if not bool(info.get("name")):
                    raise RiskBlocked("OANDA instrument is not tradeable for this account")
            except Exception as exc:
                raise RiskBlocked(str(exc)) from exc
        governor = evaluate_trade(side=side, price=quote, quantity=quantity, live=live, stop_loss_price=stop_loss_price, take_profit_price=take_profit_price, signal=signal or {})
        if governor.action != "ALLOW":
            raise RiskBlocked("Risk Governor blocked order: " + ",".join(governor.reasons))
        await risk_gate(symbol, quote, quantity, live=live, signal_timestamp=signal_timestamp, side=side, customer_id=customer_id, stop_loss_price=stop_loss_price, take_profit_price=take_profit_price, signal=signal or {})
        trade_id, created = await _create_trade(
            symbol, timeframe, side, quantity, quote, exchange, mode, signal, signal_id, cid,
            stop_loss_price or 0.0, take_profit_price or 0.0, customer_id=customer_id, trading_account_id=trading_account_id,
        )
        if not created:
            async with SessionLocal() as db:
                existing = await db.get(Trade, trade_id)
                if existing and existing.mode == "LIVE":
                    await _ensure_order_command(existing.id, customer_id=existing.customer_id, exchange=existing.exchange, symbol=existing.symbol, side=existing.side, quantity=float(existing.requested_quantity or 0), price=float(existing.requested_price or 0), stop_loss_price=float(existing.stop_loss_price or 0), take_profit_price=float(existing.take_profit_price or 0), client_order_id=existing.client_order_id)
                return {"duplicate": True, "trade_id": existing.id, "mode": existing.mode, "status": existing.status,
                        "broker_order_id": existing.broker_order_id, "client_order_id": existing.client_order_id,
                        "filled": float(existing.filled_quantity or 0.0),
                        "remaining_quantity": float(existing.remaining_quantity or 0.0),
                        "average_fill_price": float(existing.average_fill_price or 0.0)}
        reserved_cash = 0.0
        command: OrderCommand | None = None
        if customer_id is not None and settings.customer_cash_only_trading:
            async with SessionLocal() as db:
                qpos = select(Position).where(Position.customer_id == customer_id, Position.symbol == symbol, Position.quantity != 0).with_for_update()
                positions_now = (await db.execute(qpos)).scalars().all()
                signed_order = quantity if side == "buy" else -quantity
                reducing = any((p.quantity > 0 > signed_order) or (p.quantity < 0 < signed_order) for p in positions_now)
                if not reducing:
                    reserve_buffer = max(0.0, float(settings.max_slippage_bps or 0.0)) / 10_000.0
                    reserved_cash = float(quote * quantity * (1.0 + reserve_buffer))
                    try:
                        await reserve_trading(db, customer_id, reserved_cash,
                                              reference_id=f"trade:{trade_id}:open-reserve")
                        reserved_trade = await db.get(Trade, trade_id, with_for_update=True)
                        if reserved_trade:
                            reserved_trade.reserved_cash = reserved_cash
                        account_locked = (await db.execute(select(TradingAccount).where(TradingAccount.customer_id == customer_id).with_for_update())).scalar_one_or_none()
                        if account_locked:
                            account_locked.reserved_margin += reserved_cash
                            account_locked.cash_equity = max(0.0, account_locked.cash_equity)
                        await sync_wallet_from_ledger(db, customer_id, "USDT")
                        if mode == "LIVE":
                            command = await _ensure_order_command_in_session(
                                db, trade_id, customer_id=customer_id, exchange=exchange, symbol=symbol, side=side,
                                quantity=quantity, price=quote, stop_loss_price=float(stop_loss_price or 0),
                                take_profit_price=float(take_profit_price or 0), client_order_id=cid,
                            )
                        await db.commit()
                        if command is not None:
                            await db.refresh(command)
                    except ValueError as exc:
                        # The trade row was created before the ledger reservation so a
                        # successful risk pre-check cannot race into an orphaned PENDING
                        # trade when another order consumes the customer's balance first.
                        await db.rollback()
                        async with SessionLocal() as reject_db:
                            reject_trade = await reject_db.get(Trade, trade_id, with_for_update=True)
                            if reject_trade and reject_trade.status not in TERMINAL_STATUSES:
                                reject_trade.status = "REJECTED"
                                reject_trade.error = str(exc)[:2000]
                                reject_trade.updated_at = utcnow()
                                await reject_db.commit()
                        raise RiskBlocked(str(exc))
        if mode == "PAPER":
            async with SessionLocal() as db:
                t = await db.get(Trade, trade_id)
                if t.status == "SIMULATED":
                    return {"duplicate": True, "trade_id": t.id, "mode": t.mode, "status": t.status}
                profile = PROFILES.get(asset, PROFILES["crypto"])
                modeled_fill = quote * (1 + profile.slippage_bps / 10_000) if side == "buy" else quote * (1 - profile.slippage_bps / 10_000)
                fee = quantity * modeled_fill * (profile.taker_bps / 10_000)
                t.status = "SIMULATED"
                t.filled_quantity = quantity
                t.remaining_quantity = 0
                t.average_fill_price = modeled_fill
                t.notional = quantity * modeled_fill
                t.fee = fee
                await _apply_fill_to_position(db, t, quantity, modeled_fill)
                if customer_id is not None and fee > 0:
                    await settle_trading_fee(db, customer_id=customer_id, fee=fee, reference_id=f"trade:{trade_id}:fee")
                if account is not None:
                    account.cash_equity = max(0.0, account.cash_equity - fee)
                else:
                    s = await _get_state_locked(db)
                    s.cash_equity = max(0.0, s.cash_equity - fee)
                await db.commit()
            await mark_paper_equity({symbol: quote}, customer_id=customer_id)
            await audit("PAPER_ORDER", {"trade_id": trade_id, "signal_id": signal_id, "client_order_id": cid,
                                        "symbol": symbol, "side": side, "quantity": quantity})
            return {"duplicate": False, "trade_id": trade_id, "mode": "PAPER", "status": "SIMULATED", "price": quote}

        assert broker is not None
        try:
            amount = await asyncio.to_thread(broker.normalize_amount, symbol, quantity)
            if amount <= 0:
                raise RiskBlocked("Broker precision rounded quantity to zero")
            market = await asyncio.to_thread(broker.market_info, symbol)
        except Exception as exc:
            # The customer reserve was created before exchange-specific precision/limit
            # validation. If validation fails, close the local trade and release the
            # reserve atomically; otherwise capital can remain stranded indefinitely.
            async with SessionLocal() as db:
                t = await db.get(Trade, trade_id, with_for_update=True)
                if t and t.status not in TERMINAL_STATUSES:
                    t.status = "REJECTED"
                    t.error = str(exc)[:2000]
                    if customer_id is not None:
                        await _release_unneeded_order_reserve(db, t)
                    await db.commit()
            if isinstance(exc, RiskBlocked):
                raise
            raise RiskBlocked(f"Exchange order validation failed: {exc}") from exc
        if asset not in {"forex", "commodity"}:
            min_amount = ((market.get("limits") or {}).get("amount") or {}).get("min")
            max_amount = ((market.get("limits") or {}).get("amount") or {}).get("max")
            if min_amount is not None and amount < float(min_amount):
                raise RiskBlocked("Order quantity is below exchange minimum")
            if max_amount is not None and amount > float(max_amount):
                raise RiskBlocked("Order quantity exceeds exchange maximum")
            cost_limits = ((market.get("limits") or {}).get("cost") or {})
            min_cost = cost_limits.get("min")
            max_cost = cost_limits.get("max")
            order_cost = amount * quote
            if min_cost is not None and order_cost < float(min_cost):
                raise RiskBlocked("Order cost is below exchange minimum")
            if max_cost is not None and order_cost > float(max_cost):
                raise RiskBlocked("Order cost exceeds exchange maximum")

        if command is None:
            command = await _ensure_order_command(
                trade_id, customer_id=customer_id, exchange=exchange, symbol=symbol, side=side, quantity=amount,
                price=quote, stop_loss_price=float(stop_loss_price or 0),
                take_profit_price=float(take_profit_price or 0), client_order_id=cid,
            )
        lease_token: int | None = None
        try:
            reduce_only = False
            if customer_id is not None:
                async with SessionLocal() as gate_db:
                    qpos = select(Position).where(Position.customer_id == customer_id, Position.symbol == symbol, Position.quantity != 0)
                    positions = (await gate_db.execute(qpos)).scalars().all()
                    signed = amount if side == "buy" else -amount
                    reduce_only = any((p.quantity > 0 > signed) or (p.quantity < 0 < signed) for p in positions)
                    await assert_live_system_enabled(gate_db, asset=asset, customer_id=customer_id, exchange=exchange, side=side, quantity=amount, reduce_only=reduce_only)
            else:
                async with SessionLocal() as gate_db:
                    await assert_live_system_enabled(gate_db, asset=asset, customer_id=None, exchange=exchange, side=side, quantity=amount)
            _, lease_token = await _acquire_live_execution_lease(ttl_seconds=max(15, int(settings.exchange_timeout_ms / 1000) + 10))
            await _verify_live_lease(lease_token)
            await _mark_order_command(command.id, status="SUBMITTING", token=lease_token, attempts_increment=True)
            if asset in {"forex", "commodity"}:
                order = await asyncio.to_thread(
                    broker.market_order, symbol, side, amount, cid,
                    stop_loss_price, take_profit_price,
                )
            else:
                order = await asyncio.to_thread(
                    broker.market_order, symbol, side, amount, cid,
                    stop_loss_price, take_profit_price, False,
                )
        except (LiveExecutionBlocked, RiskBlocked) as exc:
            await _mark_order_command(command.id, status="BLOCKED", token=lease_token, error=str(exc))
            if customer_id is not None and reserved_cash > 0:
                async with SessionLocal() as db:
                    t = await db.get(Trade, trade_id, with_for_update=True)
                    if t and t.status not in TERMINAL_STATUSES:
                        t.status = "REJECTED"
                        t.error = str(exc)[:2000]
                        await _release_unneeded_order_reserve(db, t)
                        await db.commit()
            await _release_live_execution_lease(lease_token)
            raise
        except Exception as exc:
            # A network timeout is outcome-unknown. Keep the customer reserve locked
            # until broker reconciliation proves whether any quantity was filled.
            async with SessionLocal() as db:
                t = await db.get(Trade, trade_id)
                t.status = "UNKNOWN"
                t.error = str(exc)
                t.updated_at = utcnow()
                await db.commit()
            await _mark_order_command(command.id, status="UNKNOWN", token=lease_token, error=str(exc))
            await _release_live_execution_lease(lease_token)
            await audit("LIVE_ORDER_UNKNOWN", {"trade_id": trade_id, "client_order_id": cid, "error": str(exc)})
            raise

        broker_id = str(order.get("id") or "")
        filled = float(order.get("filled") or 0.0)
        fill_price = float(order.get("average") or order.get("price") or quote)
        status = str(order.get("status") or "open").lower()
        protection_ok = True
        protection_reason = ""
        if live and settings.require_protective_stop_for_live and filled > 0 and asset == "crypto":
            try:
                open_orders = await asyncio.to_thread(broker.fetch_open_orders, symbol)
                expected_opposite = "sell" if side == "buy" else "buy"
                stop_types = {"stop", "stop_market", "stop-loss", "stop_loss", "stop_loss_limit"}
                def _stop_matches(o: dict[str, Any]) -> bool:
                    info = o.get("info") or {}
                    nested_stop = o.get("stopLoss") or o.get("stop_loss") or info.get("stopLoss") or info.get("stop_loss") or {}
                    otype = str(o.get("type") or o.get("orderType") or info.get("orderType") or "").lower()
                    oside = str(o.get("side") or info.get("side") or "").lower()
                    trigger = o.get("triggerPrice") or o.get("stopPrice") or info.get("stopPrice") or info.get("triggerPrice")
                    if trigger is None and isinstance(nested_stop, dict):
                        trigger = nested_stop.get("triggerPrice") or nested_stop.get("stopPrice") or nested_stop.get("price")
                    try:
                        trigger_f = float(trigger) if trigger is not None else 0.0
                    except Exception:
                        trigger_f = 0.0
                    attached_stop = bool(nested_stop)
                    if oside and oside != expected_opposite:
                        return False
                    if not attached_stop and otype not in stop_types:
                        return False
                    if trigger_f <= 0:
                        return False
                    target = float(stop_loss_price or 0.0)
                    return target > 0 and abs(trigger_f - target) <= max(abs(target) * 0.003, 1e-12)
                protection_ok = any(_stop_matches(o) for o in ([order] + (open_orders or [])))
                if not protection_ok:
                    protection_reason = "No matching protective stop was visible on the exchange after entry fill"
            except Exception as exc:
                protection_ok = False
                protection_reason = f"Protective stop verification failed: {exc}"

        async with SessionLocal() as db:
            t = await db.get(Trade, trade_id)
            t.broker_order_id = broker_id
            await _apply_fill_to_position(db, t, filled, fill_price)
            if status in {"closed", "filled"} and t.remaining_quantity <= 0:
                t.status = "FILLED"
            elif filled > 0:
                t.status = "PARTIAL"
            elif status in {"canceled", "cancelled"}:
                t.status = "CANCELED"
            elif status in {"rejected"}:
                t.status = "REJECTED"
            else:
                t.status = "OPEN"
            if t.status in {"FILLED", "CANCELED", "REJECTED"}:
                await _release_unneeded_order_reserve(db, t)
            t.error = protection_reason if not protection_ok else ""
            t.updated_at = utcnow()
            cmd = await db.get(OrderCommand, command.id, with_for_update=True)
            if cmd:
                cmd.status = "SUBMITTED" if protection_ok else "PROTECTION_MISSING"
                cmd.fencing_token = int(lease_token or 0)
                cmd.broker_order_id = broker_id[:120]
                cmd.submitted_at = utcnow()
                cmd.error = protection_reason[:2000] if protection_reason else ""
                cmd.updated_at = utcnow()
            if not protection_ok and filled > 0:
                s2 = await _get_state_locked(db)
                s2.kill_switch = True
                s2.live_enabled = False
                s2.mode = "HALTED"
            await db.commit()
        await _release_live_execution_lease(lease_token)
        if not protection_ok and filled > 0:
            await open_incident(key=f"PROTECTIVE_STOP_MISSING:{trade_id}", severity="CRITICAL", category="EXECUTION_PROTECTION", summary="Protective stop could not be verified after live entry", detail={"trade_id":trade_id,"broker_order_id":broker_id,"reason":protection_reason}, customer_id=customer_id)
            await audit("PROTECTIVE_STOP_MISSING", {"trade_id":trade_id,"broker_order_id":broker_id,"reason":protection_reason})
            return {"duplicate": False, "trade_id": trade_id, "mode": "LIVE", "status": "PROTECTION_MISSING",
                    "broker_order_id": broker_id, "client_order_id": cid, "price": fill_price, "filled": filled, "halted": True}
        await audit("LIVE_ORDER_SUBMITTED", {"trade_id": trade_id, "broker_order_id": broker_id,
                                               "client_order_id": cid, "status": status, "filled": filled})
        return {"duplicate": False, "trade_id": trade_id, "mode": "LIVE", "status": status,
                "broker_order_id": broker_id, "client_order_id": cid, "price": fill_price, "filled": filled}


async def _apply_broker_snapshot(db, trade: Trade, order: dict[str, Any]):
    status = str(order.get("status") or "open").lower()
    filled = float(order.get("filled") or 0.0)
    avg = float(order.get("average") or order.get("price") or trade.average_fill_price or trade.requested_price)
    realized_delta = await _apply_fill_to_position(db, trade, filled, avg)
    if status in {"closed", "filled"} and trade.remaining_quantity <= 0:
        trade.status = "FILLED"
    elif status in {"canceled", "cancelled"}:
        trade.status = "CANCELED"
    elif status in {"rejected"}:
        trade.status = "REJECTED"
    elif filled > 0:
        trade.status = "PARTIAL"
    else:
        trade.status = "OPEN"
    if trade.status in {"FILLED", "CANCELED", "REJECTED"}:
        await _release_unneeded_order_reserve(db, trade)
    trade.updated_at = utcnow()
    return realized_delta


async def sync_live_account(exchange: str, symbols: list[str] | None = None) -> dict[str, Any]:
    cfg = BrokerConfig(exchange_id=exchange, api_key=settings.exchange_api_key, api_secret=settings.exchange_api_secret,
                       password=settings.exchange_password, sandbox=settings.broker_sandbox,
                       market_type=settings.default_market_type, timeout_ms=settings.exchange_timeout_ms)
    broker = Broker.get(cfg)
    balance = await asyncio.to_thread(broker.fetch_balance)
    total = balance.get("total") or {}
    equity = None
    for ccy in ("USDT", "USD", "USDC"):
        if ccy in total and total[ccy] is not None:
            equity = float(total[ccy])
            break
    if equity is None:
        raise RuntimeError("Could not determine quote-currency account equity from broker balance")
    positions_raw = await asyncio.to_thread(broker.fetch_positions, symbols)
    async with SessionLocal() as db:
        s = await _get_state_locked(db)
        s.equity = equity
        s.peak_equity = max(s.peak_equity, equity)
        positions_seen = set()
        for raw in positions_raw or []:
            symbol = raw.get("symbol")
            contracts = raw.get("contracts")
            if contracts is None:
                contracts = raw.get("info", {}).get("positionAmt")
            if not symbol or contracts is None:
                continue
            qty = float(contracts)
            if qty == 0:
                continue
            side = str(raw.get("side") or "").lower()
            signed_qty = abs(qty) if side == "long" else (-abs(qty) if side == "short" else qty)
            entry = float(raw.get("entryPrice") or 0.0)
            mark = float(raw.get("markPrice") or raw.get("lastPrice") or entry or 0.0)
            upnl = float(raw.get("unrealizedPnl") or 0.0)
            # This broker snapshot represents the platform account only. Customer
            # positions live on isolated Binance accounts and must never be selected
            # or overwritten by a platform reconciliation pass.
            pos = (await db.execute(
                select(Position).where(
                    Position.customer_id.is_(None),
                    Position.symbol == symbol,
                    or_(Position.exchange == exchange, Position.exchange == ""),
                ).with_for_update()
            )).scalars().first()
            if not pos:
                pos = Position(exchange=exchange, customer_id=None, symbol=symbol, quantity=signed_qty,
                               average_entry_price=entry, mark_price=mark, unrealized_pnl=upnl)
                db.add(pos)
            else:
                pos.exchange = exchange
                pos.quantity = signed_qty
                pos.average_entry_price = entry
                pos.mark_price = mark
                pos.unrealized_pnl = upnl
                pos.updated_at = utcnow()
            positions_seen.add(symbol)
        await _ensure_daily_boundary(db, s)
        await db.commit()
    return {"equity": equity, "positions_synced": len(positions_seen)}


async def reconcile_customer_live_orders(exchanges: list[str] | None = None) -> dict[str, Any]:
    """Reconcile customer-isolated live orders without requiring platform exchange credentials.

    Customer crypto execution is isolated to verified Binance subaccounts. The platform
    reconciliation loop may use a different default exchange, so customer UNKNOWN/OPEN/PARTIAL
    orders need a separate recovery pass that resolves them through their own credentials.
    """
    requested = {str(x).lower() for x in (exchanges or ["binance"]) if str(x).strip()}
    async with SessionLocal() as db:
        query = select(Trade).where(
            Trade.customer_id.is_not(None),
            Trade.status.in_(["PENDING", "OPEN", "PARTIAL", "UNKNOWN"]),
            Trade.exchange.in_(list(requested)),
        )
        trades = (await db.execute(query.order_by(Trade.updated_at).limit(200))).scalars().all()
        snapshots = [(t.id, t.customer_id, t.exchange, t.symbol, t.broker_order_id, t.client_order_id) for t in trades]
    results = []
    for trade_id, customer_id, exchange, symbol, broker_order_id, client_order_id in snapshots:
        try:
            if str(exchange).lower() != "binance":
                raise RuntimeError("Customer live reconciliation is only enabled for Binance isolation")
            async with SessionLocal() as credential_db:
                customer_binance = (await credential_db.execute(
                    select(CustomerBinanceAccount).where(CustomerBinanceAccount.customer_id == customer_id)
                )).scalar_one_or_none()
            broker = build_customer_binance_broker(
                customer_binance, timeout_ms=settings.exchange_timeout_ms, sandbox=settings.broker_sandbox
            )
            order = None
            if broker_order_id:
                order = await asyncio.to_thread(broker.fetch_order, broker_order_id, symbol)
            if order is None:
                opens = await asyncio.to_thread(broker.fetch_open_orders, symbol)
                order = next((o for o in opens if str(o.get("clientOrderId") or o.get("info", {}).get("clientOrderId") or "") == client_order_id), None)
                if order is None:
                    history = await asyncio.to_thread(broker.fetch_orders, symbol)
                    order = next((o for o in history if str(o.get("clientOrderId") or o.get("info", {}).get("clientOrderId") or "") == client_order_id), None)
            if order is None:
                async with SessionLocal() as incident_db:
                    unresolved_trade = await incident_db.get(Trade, trade_id)
                if unresolved_trade:
                    await open_incident(
                        key=f"CUSTOMER_ORDER_UNRESOLVED:{trade_id}",
                        severity="CRITICAL" if unresolved_trade.status == "UNKNOWN" else "HIGH",
                        category="RECONCILIATION",
                        summary="Customer exchange order could not be reconciled",
                        detail={"trade_id": trade_id, "customer_id": customer_id, "exchange": exchange, "symbol": symbol, "broker_order_id": broker_order_id, "client_order_id": client_order_id, "status": unresolved_trade.status},
                        customer_id=customer_id,
                    )
                results.append({"trade_id": trade_id, "customer_id": customer_id, "resolved": False, "reason": "order_not_found"})
                continue
            async with SessionLocal() as db:
                t = await db.get(Trade, trade_id, with_for_update=True)
                if not t:
                    results.append({"trade_id": trade_id, "customer_id": customer_id, "resolved": False, "reason": "trade_missing"})
                    continue
                await _apply_broker_snapshot(db, t, order)
                command_row = (await db.execute(select(OrderCommand).where(OrderCommand.trade_id == t.id).with_for_update())).scalar_one_or_none()
                if command_row:
                    command_row.status = "RECONCILED"
                    if order.get("id"):
                        command_row.broker_order_id = str(order["id"])[:120]
                    command_row.error = ""
                    command_row.updated_at = utcnow()
                await db.commit()
                results.append({"trade_id": t.id, "customer_id": customer_id, "status": t.status, "resolved": True})
        except Exception as exc:
            results.append({"trade_id": trade_id, "customer_id": customer_id, "resolved": False, "error": str(exc)[:1000]})
    return {"results": results, "checked": len(snapshots)}


async def reconcile(exchange: str, symbol: str | None = None) -> dict[str, Any]:
    is_oanda = exchange.lower() == "oanda"
    if is_oanda:
        if not settings.oanda_account_id or not settings.oanda_api_token:
            raise RuntimeError("OANDA credentials are not configured")
        broker = OandaBroker(OandaConfig(settings.oanda_account_id, settings.oanda_api_token, settings.oanda_practice, settings.oanda_timeout_seconds))
    else:
        cfg = BrokerConfig(exchange_id=exchange, api_key=settings.exchange_api_key, api_secret=settings.exchange_api_secret,
                           password=settings.exchange_password, sandbox=settings.broker_sandbox,
                           market_type=settings.default_market_type, timeout_ms=settings.exchange_timeout_ms)
        broker = Broker.get(cfg)
    async with SessionLocal() as db:
        query = select(Trade).where(Trade.exchange == exchange,
                                    Trade.status.in_(["PENDING", "OPEN", "PARTIAL", "UNKNOWN"]))
        if symbol:
            query = query.where(Trade.symbol == symbol)
        trades = (await db.execute(query)).scalars().all()
        snapshots = [(t.id, t.broker_order_id, t.symbol, t.client_order_id) for t in trades]
    results = []
    oanda_changes = None
    oanda_previous_transaction_id = ""
    if is_oanda:
        async with SessionLocal() as db:
            cursor = (await db.execute(select(OandaReconciliationState).where(
                OandaReconciliationState.account_id == settings.oanda_account_id
            ).with_for_update())).scalar_one_or_none()
            if not cursor:
                cursor = OandaReconciliationState(
                    account_id=settings.oanda_account_id,
                    environment="practice",
                )
                db.add(cursor)
                await db.commit()
            if not cursor.last_transaction_id:
                snapshot = await asyncio.to_thread(broker.account)
                cursor.last_transaction_id = str(snapshot.get("lastTransactionID") or snapshot.get("account", {}).get("lastTransactionID") or "")
            if cursor.last_transaction_id:
                try:
                    oanda_previous_transaction_id = str(cursor.last_transaction_id)
                    oanda_changes = await asyncio.to_thread(broker.account_changes, cursor.last_transaction_id)
                    cursor.last_transaction_id = str(oanda_changes.get("lastTransactionID") or cursor.last_transaction_id)
                    cursor.status = "READY"
                    cursor.last_error = ""
                    cursor.last_sync_at = utcnow()
                    await db.commit()
                except Exception as exc:
                    cursor.status = "ERROR"
                    cursor.last_error = str(exc)
                    cursor.last_sync_at = utcnow()
                    await db.commit()
                    raise
    for trade_id, broker_order_id, trade_symbol, cid in snapshots:
        trade_broker = broker
        trade_is_customer = False
        try:
            async with SessionLocal() as lookup_db:
                trade_row = await lookup_db.get(Trade, trade_id)
                trade_customer_id = trade_row.customer_id if trade_row else None
                trade_exchange = str(trade_row.exchange or exchange) if trade_row else exchange
            if trade_customer_id is not None and not is_oanda:
                if trade_exchange.lower() != "binance":
                    raise RuntimeError("Customer reconciliation requires the configured isolated exchange adapter")
                async with SessionLocal() as credential_db:
                    from .db import CustomerBinanceAccount
                    customer_binance = (await credential_db.execute(
                        select(CustomerBinanceAccount).where(CustomerBinanceAccount.customer_id == trade_customer_id)
                    )).scalar_one_or_none()
                trade_broker = build_customer_binance_broker(
                    customer_binance, timeout_ms=settings.exchange_timeout_ms, sandbox=settings.broker_sandbox
                )
                trade_is_customer = True
            order = None
            if is_oanda:
                if broker_order_id:
                    order = await asyncio.to_thread(broker.order, broker_order_id)
                if order is None:
                    order = await asyncio.to_thread(broker.resolve_unknown_order, cid, oanda_previous_transaction_id or None)
            elif broker_order_id:
                order = await asyncio.to_thread(trade_broker.fetch_order, broker_order_id, trade_symbol)
            else:
                opens = await asyncio.to_thread(trade_broker.fetch_open_orders, trade_symbol)
                order = next((o for o in opens if str(o.get("clientOrderId") or o.get("info", {}).get("clientOrderId") or "") == cid), None)
                if order is None:
                    history = await asyncio.to_thread(trade_broker.fetch_orders, trade_symbol)
                    order = next((o for o in history if str(o.get("clientOrderId") or o.get("info", {}).get("clientOrderId") or "") == cid), None)
            if order is None:
                results.append({"trade_id": trade_id, "resolved": False})
                continue
            async with SessionLocal() as db:
                t = await db.get(Trade, trade_id, with_for_update=True)
                if not t:
                    results.append({"trade_id": trade_id, "resolved": False, "error": "trade disappeared"})
                    continue
                if not t.broker_order_id and order.get("id"):
                    t.broker_order_id = str(order["id"])
                await _apply_broker_snapshot(db, t, order)
                command_row = (await db.execute(select(OrderCommand).where(OrderCommand.trade_id == t.id).with_for_update())).scalar_one_or_none()
                if command_row:
                    command_row.status = "RECONCILED"
                    if order.get("id"):
                        command_row.broker_order_id = str(order["id"])[:120]
                    command_row.error = ""
                    command_row.updated_at = utcnow()
                await db.commit()
                results.append({"trade_id": t.id, "status": t.status, "resolved": True})
        except Exception as exc:
            results.append({"trade_id": trade_id, "resolved": False, "error": str(exc)})
    if is_oanda:
        try:
            account_data = await asyncio.to_thread(broker.account)
            account = {"balance": account_data.get("account", {}).get("balance"),
                       "NAV": account_data.get("account", {}).get("NAV"),
                       "marginAvailable": account_data.get("account", {}).get("marginAvailable")}
        except Exception as exc:
            account = {"error": str(exc)}
        finally:
            broker.close()
    elif settings.live_trading_enabled and not settings.paper_trading:
        try:
            account = await sync_live_account(exchange, [symbol] if symbol else None)
        except Exception as exc:
            account = {"error": str(exc)}
    else:
        account = {"paper": True}
    reconciliation_meta = None
    if is_oanda:
        reconciliation_meta = {
            "cursor_advanced": bool(oanda_changes),
            "last_transaction_id": str((oanda_changes or {}).get("lastTransactionID") or ""),
            "changes": {k: len(v) if isinstance(v, list) else bool(v) for k, v in ((oanda_changes or {}).get("changes") or {}).items()},
        }
    await audit("RECONCILIATION", {"exchange": exchange, "symbol": symbol, "results": results, "account": account, "reconciliation": reconciliation_meta})
    return {"results": results, "account": account, "reconciliation": reconciliation_meta}


async def emergency_stop(exchange: str | None = None):
    """Halt new live execution first, then cancel platform and customer open orders."""
    async with SessionLocal() as db:
        s = await _get_state_locked(db)
        s.kill_switch = True
        s.live_enabled = False
        s.mode = "HALTED"
        await db.commit()

    canceled: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    cancel_error = None

    if exchange and exchange.lower() == "oanda":
        if settings.oanda_account_id and settings.oanda_api_token:
            broker = OandaBroker(OandaConfig(settings.oanda_account_id, settings.oanda_api_token, settings.oanda_practice, settings.oanda_timeout_seconds))
            try:
                orders = await asyncio.to_thread(broker.orders)
                for order in orders:
                    order_id = str(order.get("id") or "")
                    state = str(order.get("state") or "").upper()
                    if order_id and state in {"PENDING", "OPEN"}:
                        await asyncio.to_thread(broker.cancel_order, order_id)
                        canceled.append({"scope": "platform_oanda", "order_id": order_id})
            except Exception as exc:
                cancel_error = str(exc)
                failures.append({"scope": "platform_oanda", "error": cancel_error})
                await audit("EMERGENCY_CANCEL_FAILED", {"exchange": exchange, "error": cancel_error})
            finally:
                broker.close()
        else:
            cancel_error = "OANDA credentials are not configured"
            failures.append({"scope": "platform_oanda", "error": cancel_error})
    elif exchange and settings.exchange_api_key and settings.exchange_api_secret:
        cfg = BrokerConfig(exchange_id=exchange, api_key=settings.exchange_api_key, api_secret=settings.exchange_api_secret,
                           password=settings.exchange_password, sandbox=settings.broker_sandbox,
                           market_type=settings.default_market_type, timeout_ms=settings.exchange_timeout_ms)
        broker = Broker.get(cfg)
        try:
            rows = await asyncio.to_thread(broker.cancel_all_orders)
            for item in rows or []:
                canceled.append({"scope": "platform_exchange", "order_id": str(item.get("id") or "")})
        except Exception as exc:
            cancel_error = str(exc)
            failures.append({"scope": "platform_exchange", "error": cancel_error})
            await audit("EMERGENCY_CANCEL_FAILED", {"exchange": exchange, "error": cancel_error})

    # Customer live trading uses isolated Binance credentials; kill must sweep them too.
    if settings.customer_live_trading_enabled:
        async with SessionLocal() as db:
            customer_accounts = (await db.execute(
                select(CustomerBinanceAccount).where(
                    CustomerBinanceAccount.status == "VERIFIED",
                    CustomerBinanceAccount.can_trade.is_(True),
                )
            )).scalars().all()
        for account in customer_accounts:
            try:
                broker = await asyncio.to_thread(
                    build_customer_binance_broker, account, timeout_ms=settings.exchange_timeout_ms, sandbox=False
                )
                rows = await asyncio.to_thread(broker.cancel_all_orders)
                for item in rows or []:
                    canceled.append({"scope": f"customer:{account.customer_id}", "order_id": str(item.get("id") or "")})
            except Exception as exc:
                failure = {"scope": f"customer:{account.customer_id}", "error": str(exc)[:1000]}
                failures.append(failure)
                try:
                    await open_incident(
                        key=f"EMERGENCY_CANCEL_FAILED:CUSTOMER:{account.customer_id}",
                        severity="CRITICAL", category="EMERGENCY_STOP",
                        summary="Emergency stop could not cancel all customer exchange orders",
                        detail=failure, customer_id=account.customer_id,
                    )
                except Exception:
                    pass

    await audit("EMERGENCY_STOP", {
        "exchange": exchange, "canceled_count": len(canceled),
        "failure_count": len(failures), "cancel_error": cancel_error,
    })
    return {"ok": True, "canceled_count": len(canceled), "failure_count": len(failures),
            "cancel_error": cancel_error, "failures": failures, "mode": "HALTED"}

