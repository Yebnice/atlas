from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .config import settings


class AIProviderError(RuntimeError):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].lstrip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AIProviderError(f"AI provider returned non-JSON output: {exc}") from exc
    if not isinstance(value, dict):
        raise AIProviderError("AI provider returned JSON that is not an object")
    return value


async def _gemini_json(prompt: str, *, timeout: float = 30.0, system_instruction: str | None = None, model: str | None = None) -> dict[str, Any]:
    if not settings.gemini_api_key:
        raise AIProviderError("GEMINI_API_KEY is not configured")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model or settings.gemini_model}:generateContent"
    payload = {
        "systemInstruction": {
            "parts": [{"text": (
                system_instruction or ("You are Atlas Trading OS's research analyst. Analyze supplied market research only. "
                "Do not place trades, invent market data, or give guaranteed outcomes. Return JSON only.")
            )}]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    headers = {"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError("Gemini response did not contain generated text") from exc
    return _extract_json(text)


async def _groq_json(prompt: str, *, timeout: float = 30.0, system_instruction: str | None = None, model: str | None = None) -> dict[str, Any]:
    if not settings.groq_api_key:
        raise AIProviderError("GROQ_API_KEY is not configured")
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model or settings.groq_model,
        "messages": [
            {"role": "system", "content": (
                system_instruction or ("You are Atlas Trading OS's fast market-analysis assistant. Analyze supplied research only. "
                "Do not place trades, invent market data, or give guaranteed outcomes. Return JSON only.")
            )},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_completion_tokens": settings.groq_max_completion_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError("Groq response did not contain generated text") from exc
    return _extract_json(text)


def _prompt(research: dict[str, Any], intelligence: dict[str, Any]) -> str:
    compact = {
        "research": research,
        "news_summary": intelligence.get("news_summary", {}),
        "source_failures": intelligence.get("failures", {}),
    }
    return (
        "Review this Atlas research packet. Return an object with keys: "
        "regime_assessment, key_observations (array), data_quality_flags (array), "
        "strategy_watchlist (array), confidence (0..1), and research_only_summary. "
        "Do not output buy/sell instructions.\n\n" + json.dumps(compact, default=str)
    )


async def dual_ai_research_review(research: dict[str, Any], intelligence: dict[str, Any]) -> dict[str, Any]:
    """Run Gemini and Groq independently and return both auditable outputs.

    Gemini is the primary research/deeper-analysis provider; Groq is the fast
    secondary analysis provider. Neither output has authority to execute orders.
    """
    prompt = _prompt(research, intelligence)
    results = await asyncio.gather(
        _gemini_json(prompt),
        _groq_json(prompt),
        return_exceptions=True,
    )
    providers: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name, result in zip(("gemini", "groq"), results):
        if isinstance(result, Exception):
            errors[name] = str(result)
        else:
            providers[name] = result
    return {
        "mode": "GEMINI_GROQ_DUAL_AI",
        "providers": providers,
        "errors": errors,
        "execution_authority": False,
    }


async def dual_ai_trade_safety_review(trade_packet: dict[str, Any]) -> dict[str, Any]:
    """Independent Gemini/Groq safety veto for a deterministic trade plan.

    Providers may only approve/reject the supplied plan. They cannot change entry,
    stop, target, size, or execution mode. Missing/failed providers are unsafe.
    """
    prompt = (
        "Review this proposed Atlas trade plan for safety only. Return JSON with keys "
        "safe (boolean), confidence (0..1), reasons (array), and data_quality_flags (array). "
        "Do not change or invent entry, stop, target, side, quantity, or prices. Reject if "
        "the supplied plan is internally inconsistent, lacks risk controls, or market/data "
        "quality is insufficient. This is a veto check, not a trading instruction.\n\n"
        + json.dumps(trade_packet, default=str)
    )
    results = await asyncio.gather(
        _gemini_json(prompt),
        _groq_json(prompt),
        return_exceptions=True,
    )
    providers: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name, result in zip(("gemini", "groq"), results):
        if isinstance(result, Exception):
            errors[name] = str(result)
        else:
            providers[name] = result
    decisions = []
    for name in ("gemini", "groq"):
        value = providers.get(name)
        decisions.append(bool(value and value.get("safe") is True))
    configured = bool(settings.gemini_api_key or settings.groq_api_key)
    return {
        "mode": "GEMINI_GROQ_TRADE_SAFETY_VETO",
        "safe": bool(len(decisions) == 2 and all(decisions) and not errors),
        "configured": configured,
        "providers": providers,
        "errors": errors,
        "execution_authority": False,
    }
