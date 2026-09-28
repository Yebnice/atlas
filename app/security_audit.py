"""Second-copy security audit sink for Cloud Logging / external log retention."""
from __future__ import annotations
import json, logging, sys
from datetime import datetime, timezone
from .config import settings

_log = logging.getLogger("atlas.security_audit")

_SENSITIVE_KEY_PARTS = ("token", "secret", "password", "api_key", "api_secret", "authorization", "private_key", "seed", "mnemonic", "ciphertext")

def _redact(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _SENSITIVE_KEY_PARTS):
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = _redact(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value

def emit_security_audit(*, event: str, actor_id: str, detail: dict, event_hash: str = "") -> bool:
    if not settings.external_security_audit_enabled:
        return not settings.external_security_audit_required
    payload = {
        "atlas_security_audit": True,
        "event": str(event),
        "actor_id": str(actor_id or "system"),
        "event_hash": str(event_hash or ""),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "detail": _redact(detail),
    }
    try:
        # Cloud Run / GCE captures stdout/stderr in Cloud Logging. Production deployment
        # must route this logger to a dedicated retention-locked log bucket. We never put
        # secrets or decrypted sensitive fields into this external copy.
        print(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str), file=sys.stdout, flush=True)
        return True
    except Exception:
        _log.exception("external security audit sink failed")
        return False
