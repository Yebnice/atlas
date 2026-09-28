from __future__ import annotations
import time
import secrets
from contextvars import ContextVar
try:
    from redis.asyncio import Redis
except ImportError:  # optional in local test environments; production installs requirements.txt
    Redis = None
from .config import settings

_client: Redis | None = None
_lock_tokens: ContextVar[dict[str, str] | None] = ContextVar("atlas_lock_tokens", default=None)

def redis_enabled() -> bool:
    return bool(settings.redis_url)

async def check_redis() -> bool:
    global _client
    if not settings.redis_url:
        return settings.environment != "production" or not settings.distributed_rate_limit_required
    if Redis is None:
        return False
    try:
        if _client is None:
            _client = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        return bool(await _client.ping())
    except Exception:
        return False

async def allow_rate_limit(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    if not settings.redis_url:
        if settings.environment == "production" and settings.distributed_rate_limit_required:
            return False, window_seconds
        return True, 0
    global _client
    if Redis is None:
        return (settings.environment != "production"), 0
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    bucket = int(time.time() // window_seconds)
    redis_key = f"atlas:rl:{key}:{bucket}"
    try:
        count = int(await _client.incr(redis_key))
        if count == 1:
            await _client.expire(redis_key, window_seconds + 2)
        remaining = max(0, limit - count)
        return count <= limit, remaining
    except Exception:
        # Fail closed in production; local development may continue without Redis.
        return (settings.environment != "production"), 0

async def acquire_lock(key: str, ttl_seconds: int = 900) -> bool:
    """Cross-instance Redis lock with owner-token release."""
    if not settings.redis_url:
        return settings.environment != "production"
    if Redis is None:
        return False
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    token = secrets.token_urlsafe(24)
    try:
        ok = bool(await _client.set(f"atlas:lock:{key}", token, ex=max(30, ttl_seconds), nx=True))
        if ok:
            owned = dict(_lock_tokens.get() or {})
            owned[key] = token
            _lock_tokens.set(owned)
        return ok
    except Exception:
        return False


async def refresh_lock(key: str, ttl_seconds: int = 900) -> bool:
    """Extend a Redis lease only if this process still owns it."""
    if not _client:
        return False
    owned = dict(_lock_tokens.get() or {})
    token = owned.get(key)
    if not token:
        return False
    try:
        result = await _client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end",
            1, f"atlas:lock:{key}", token, max(30, ttl_seconds),
        )
        return bool(result)
    except Exception:
        return False


async def release_lock(key: str) -> None:
    if not _client:
        return
    owned = dict(_lock_tokens.get() or {})
    token = owned.pop(key, None)
    _lock_tokens.set(owned)
    if not token:
        return
    try:
        await _client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1, f"atlas:lock:{key}", token,
        )
    except Exception:
        pass
