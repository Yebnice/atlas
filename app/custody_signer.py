from __future__ import annotations
import hashlib,hmac,json
from .config import settings

class CustodySignerError(RuntimeError): pass

def custody_signing_required() -> bool:
    return bool(settings.external_custody_signer_required)

def validate_signer_config() -> None:
    if settings.external_custody_signer_required and (not settings.external_custody_signer_url or not settings.external_custody_signer_hmac_secret):
        raise CustodySignerError("External custody signer is required but not configured")

def sign_request_payload(payload: dict) -> tuple[str,str]:
    """Create a deterministic HMAC-authenticated signer request envelope.
    The actual private-key/MPC operation remains outside Atlas; this function only
    constructs the request contract.
    """
    validate_signer_config()
    body=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str)
    digest=hashlib.sha256(body.encode()).hexdigest()
    mac=hmac.new(settings.external_custody_signer_hmac_secret.encode(),digest.encode(),hashlib.sha256).hexdigest()
    return digest,mac
