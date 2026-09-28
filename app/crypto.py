"""Versioned application-layer authenticated encryption for sensitive DB fields."""
from __future__ import annotations
import json
from cryptography.fernet import Fernet, InvalidToken

_PREFIX = "enc:"
_LEGACY_PREFIX = "enc:v1:"


def _keyring() -> dict[str, str]:
    from .config import settings
    raw = str(settings.app_encryption_keys_json or "").strip()
    keys: dict[str, str] = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                keys = {str(k): str(v).strip() for k, v in parsed.items() if str(v).strip()}
        except Exception as exc:
            raise RuntimeError("APP_ENCRYPTION_KEYS_JSON must be valid JSON object") from exc
    # Backward compatibility: legacy APP_ENCRYPTION_KEY is treated as v1 unless a
    # versioned entry already exists. This permits an in-place migration without
    # re-encrypting every row at deployment time.
    legacy = str(settings.app_encryption_key or "").strip()
    if legacy and "v1" not in keys:
        keys["v1"] = legacy
    return keys


def _fernet_for(key_id: str) -> Fernet:
    keys = _keyring()
    raw = keys.get(str(key_id))
    if not raw:
        raise RuntimeError(f"Encryption key {key_id!r} is not configured")
    try:
        return Fernet(raw.encode())
    except Exception as exc:
        raise RuntimeError(f"Encryption key {key_id!r} is invalid") from exc


def _active_key() -> tuple[str, Fernet]:
    from .config import settings
    key_id = str(settings.app_encryption_active_key_id or "v2").strip()
    return key_id, _fernet_for(key_id)


def encrypt_text(value: str | None) -> str:
    if value is None:
        return ""
    value = str(value)
    if not value or value.startswith(_PREFIX):
        return value
    key_id, f = _active_key()
    token = f.encrypt(value.encode("utf-8")).decode("ascii")
    return f"enc:{key_id}:{token}"


def decrypt_text(value: str | None) -> str:
    if value is None:
        return ""
    value = str(value)
    if not value:
        return value
    if value.startswith("enc:"):
        parts = value.split(":", 2)
        if len(parts) != 3:
            raise RuntimeError("Malformed encrypted database value")
        key_id, token = parts[1], parts[2]
        try:
            return _fernet_for(key_id).decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("Encrypted database value could not be authenticated") from exc
    # Legacy ciphertext written by 3.10.37 and earlier.
    if value.startswith(_LEGACY_PREFIX):
        try:
            return _fernet_for("v1").decrypt(value[len(_LEGACY_PREFIX):].encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("Legacy encrypted database value could not be authenticated") from exc
    from .config import settings
    if settings.environment.lower() in {"production", "staging"}:
        raise RuntimeError("Unencrypted sensitive database value detected outside development")
    return value


def rotate_ciphertext(value: str | None) -> str:
    """Decrypt with the existing key and re-encrypt using the configured active key."""
    plain = decrypt_text(value)
    return encrypt_text(plain)



def validate_encryption_config() -> dict:
    """Validate the active encryption keyring used for new writes.

    The versioned keyring is authoritative when present; the legacy single key is
    accepted only as a backwards-compatible v1 source during migration.
    """
    from .config import settings
    keys = _keyring()
    active = str(settings.app_encryption_active_key_id or "").strip()
    if not active:
        raise RuntimeError("APP_ENCRYPTION_ACTIVE_KEY_ID must be configured")
    if active not in keys:
        raise RuntimeError(f"Active encryption key {active!r} is not configured")
    # Instantiate once so malformed Fernet material fails readiness/startup.
    _fernet_for(active)
    return {"active_key_id": active, "configured_key_ids": sorted(keys.keys()),
            "legacy_key_present": bool(str(settings.app_encryption_key or "").strip())}

def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")
