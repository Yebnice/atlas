from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import settings
from .ai_providers import AIProviderError, _gemini_json, _groq_json
from .strategy_evidence import evidence_for


ALLOWED_TIMEFRAMES = {"5m", "15m", "30m", "1h", "4h", "1d"}
ALLOWED_ASSETS = {"crypto", "forex", "commodity"}
ALLOWED_DIRECTIONS = {"LONG", "SHORT", "BOTH", "AUTO"}
ALLOWED_STRATEGY_FAMILIES = {"TREND", "MOMENTUM", "BREAKOUT", "MEAN_REVERSION", "ENSEMBLE"}


class StrategyCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=2, max_length=60)
    rule: str = Field(min_length=3, max_length=500)
    timeframe: str | None = Field(default=None, max_length=10)

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value: str | None) -> str | None:
        if value is not None and value not in ALLOWED_TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe: {value}")
        return value


class AIStrategySpec(BaseModel):
    """LLM output contract. It describes a strategy but has no execution authority."""

    model_config = ConfigDict(extra="forbid")
    version: Literal["atlas-strategy-v1"] = "atlas-strategy-v1"
    title: str = Field(min_length=2, max_length=120)
    summary: str = Field(min_length=10, max_length=1000)
    asset: Literal["crypto", "forex", "commodity"]
    symbols: list[str] = Field(min_length=1, max_length=10)
    timeframes: list[str] = Field(min_length=1, max_length=5)
    direction: Literal["LONG", "SHORT", "BOTH", "AUTO"]
    strategy_family: Literal["TREND", "MOMENTUM", "BREAKOUT", "MEAN_REVERSION", "ENSEMBLE"]
    entry_conditions: list[StrategyCondition] = Field(min_length=1, max_length=12)
    exit_conditions: list[StrategyCondition] = Field(min_length=1, max_length=8)
    risk_per_trade: float = Field(gt=0, le=0.05)
    stop_loss_atr: float | None = Field(default=None, gt=0, le=10)
    take_profit_rr: float | None = Field(default=None, gt=0, le=10)
    sessions: list[str] = Field(default_factory=list, max_length=8)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    validation_warnings: list[str] = Field(default_factory=list, max_length=12)
    requires_backtest: Literal[True] = True
    requires_walk_forward: Literal[True] = True
    execution_mode: Literal["PAPER_SHADOW_ONLY"] = "PAPER_SHADOW_ONLY"
    implementation_status: Literal["ATLAS_SUPPORTED_FAMILY"] = "ATLAS_SUPPORTED_FAMILY"

    @field_validator("timeframes")
    @classmethod
    def validate_timeframes(cls, values: list[str]) -> list[str]:
        if any(v not in ALLOWED_TIMEFRAMES for v in values):
            raise ValueError(f"Unsupported timeframe; allowed: {sorted(ALLOWED_TIMEFRAMES)}")
        return list(dict.fromkeys(values))

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, values: list[str]) -> list[str]:
        cleaned = [str(v).strip() for v in values if str(v).strip()]
        if not cleaned:
            raise ValueError("At least one symbol is required")
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def validate_risk_contract(self) -> "AIStrategySpec":
        if self.risk_per_trade > settings.risk_per_trade:
            self.validation_warnings.append(
                f"Requested AI risk was capped at the platform maximum of {settings.risk_per_trade:.4f}."
            )
            self.risk_per_trade = settings.risk_per_trade
        return self


SYSTEM_PROMPT = """You are Atlas Strategy Intelligence, a trading-strategy design assistant.
Create a structured strategy specification from the user's natural-language request.
You are NOT a broker, order executor, portfolio manager, or source of guaranteed returns.
Never claim that a strategy is profitable or safe merely because it sounds plausible.
Never invent current prices, market conditions, news, or backtest results.
Only describe rules that can later be validated and backtested by Atlas.
Use only these timeframes: 5m, 15m, 30m, 1h, 4h, 1d.
Use only these asset classes: crypto, forex, commodity.
Every strategy must contain explicit entry and exit conditions, risk controls, and both
backtest and walk-forward requirements. Select exactly one supported strategy_family: TREND,
MOMENTUM, BREAKOUT, MEAN_REVERSION, or ENSEMBLE. Atlas will validate that family; individual
AI conditions are specifications and must not be presented as already backtested unless Atlas
compiled and tested them. Keep execution_mode exactly PAPER_SHADOW_ONLY.
Return JSON only matching the requested schema. Do not include markdown."""


def _strategy_prompt(prompt: str, name: str) -> str:
    return (
        f"Requested strategy name: {name}\n"
        f"User strategy request:\n{prompt}\n\n"
        "Produce an Atlas StrategySpec JSON object with these fields: "
        "version, title, summary, asset, symbols, timeframes, direction, strategy_family, entry_conditions, "
        "exit_conditions, risk_per_trade, stop_loss_atr, take_profit_rr, sessions, assumptions, "
        "validation_warnings, requires_backtest, requires_walk_forward, execution_mode, implementation_status. "
        "Set strategy_family to exactly one of TREND, MOMENTUM, BREAKOUT, MEAN_REVERSION, or ENSEMBLE. "
        "Use the platform risk limit as the maximum risk_per_trade. If the request asks for "
        "unsupported or ambiguous behavior, record it in validation_warnings rather than inventing it."
    )


async def _generate_with_provider(provider: str, prompt: str) -> dict[str, Any]:
    if provider == "gemini":
        return await _gemini_json(
            prompt,
            system_instruction=SYSTEM_PROMPT,
            model=settings.gemini_strategy_model or settings.gemini_model,
        )
    return await _groq_json(
        prompt,
        system_instruction=SYSTEM_PROMPT,
        model=settings.groq_strategy_model or settings.groq_model,
    )


def _apply_market_context(spec: AIStrategySpec, *, asset: str | None = None, symbol: str | None = None, timeframe: str | None = None) -> AIStrategySpec:
    """Bind an AI draft to the market selected by the user before persistence/backtest."""
    warnings = list(spec.validation_warnings)
    data = spec.model_dump()
    if asset and spec.asset != asset:
        warnings.append(f"AI asset overridden to the selected market asset: {asset}.")
        data["asset"] = asset
    if symbol and (not spec.symbols or symbol not in spec.symbols):
        warnings.append(f"AI symbol overridden to the selected market symbol: {symbol}.")
        data["symbols"] = [symbol]
    elif symbol:
        data["symbols"] = [symbol]
    if timeframe and (not spec.timeframes or timeframe not in spec.timeframes):
        warnings.append(f"AI timeframe overridden to the selected market timeframe: {timeframe}.")
        data["timeframes"] = [timeframe]
    elif timeframe:
        data["timeframes"] = [timeframe]
    data["validation_warnings"] = warnings[:12]
    return AIStrategySpec.model_validate(data)


async def generate_strategy_draft(*, prompt: str, name: str, asset: str | None = None, symbol: str | None = None, timeframe: str | None = None) -> dict[str, Any]:
    """Generate a real LLM strategy draft, validate it, and return an auditable result.

    Gemini is primary; Groq is a configured fallback. Neither provider can execute orders.
    No deterministic keyword parser is used as a fallback because that would silently
    reintroduce the capability mismatch this endpoint is designed to remove.
    """
    if not settings.gemini_api_key and not settings.groq_api_key:
        raise AIProviderError("No AI strategy provider is configured")

    provider_errors: dict[str, str] = {}
    provider_order = ["gemini", "groq"] if settings.gemini_api_key else ["groq"]
    if settings.gemini_api_key and settings.groq_api_key:
        provider_order = ["gemini", "groq"]

    raw: dict[str, Any] | None = None
    provider_used = ""
    for provider in provider_order:
        try:
            raw = await _generate_with_provider(provider, _strategy_prompt(prompt, name))
            provider_used = provider
            break
        except Exception as exc:
            provider_errors[provider] = str(exc)

    if raw is None:
        raise AIProviderError("All configured AI strategy providers failed: " + "; ".join(
            f"{k}: {v}" for k, v in provider_errors.items()
        ))

    try:
        spec = AIStrategySpec.model_validate(raw)
        spec = _apply_market_context(spec, asset=asset, symbol=symbol, timeframe=timeframe)
    except Exception as exc:
        raise AIProviderError(f"AI strategy failed schema validation: {exc}") from exc

    family_key = {"TREND":"trend", "MOMENTUM":"momentum", "BREAKOUT":"breakout", "MEAN_REVERSION":"mean_reversion", "ENSEMBLE":"ensemble"}[spec.strategy_family]
    return {
        "strategy": spec.model_dump(),
        "evidence": evidence_for(family_key),
        "ai": {
            "provider": provider_used,
            "model": settings.gemini_strategy_model if provider_used == "gemini" else settings.groq_strategy_model,
            "fallback_used": provider_used != "gemini",
            "provider_errors": provider_errors,
            "execution_authority": False,
            "requires_backtest": True,
            "requires_walk_forward": True,
        },
    }
