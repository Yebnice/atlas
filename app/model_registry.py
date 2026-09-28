from __future__ import annotations
import base64
import hashlib, hmac, os, shutil
from pathlib import Path
from .config import settings

def sha256_file(path: str | Path) -> str:
    h=hashlib.sha256()
    with open(path,"rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def artifact_signature(digest: str) -> str:
    """Sign a model digest with Ed25519; legacy HMAC is migration-only."""
    private_pem = str(settings.model_signing_private_key or "")
    if private_pem:
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            key = load_pem_private_key(private_pem.encode(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                return ""
            return base64.urlsafe_b64encode(key.sign(digest.encode())).decode().rstrip("=")
        except Exception:
            return ""
    key = str(settings.model_signing_key or "")
    if not key:
        return ""
    return hmac.new(key.encode(), digest.encode(), hashlib.sha256).hexdigest()

def verify_model_file(model_path: str | Path, expected_sha256: str, expected_signature: str = "") -> bool:
    p=Path(model_path)
    if not p.exists() or not expected_sha256:
        return False
    try:
        digest = sha256_file(p).lower()
        if digest != str(expected_sha256).lower():
            return False
        required = str(expected_signature or "")
        if not required:
            meta = p.with_suffix(p.suffix + ".meta.json")
            if meta.exists():
                import json
                try:
                    payload = json.loads(meta.read_text())
                    required = str(payload.get("manifest_signature") or "")
                except Exception:
                    required = ""
        if required:
            return verify_artifact_signature(digest, required)
        # Production live models require an independent manifest signature.
        if settings.environment in {"staging", "production"} and settings.model_integrity_required_for_live:
            return False
        return True
    except OSError: return False

def backup_champion(model_path: str | Path) -> Path | None:
    p=Path(model_path)
    if not p.exists(): return None
    backup=p.with_name(p.name+".previous")
    shutil.copy2(p, backup)
    meta=p.with_suffix(p.suffix+".meta.json")
    if meta.exists(): shutil.copy2(meta, Path(str(backup)+".meta.json"))
    return backup

def rollback_champion(model_path: str | Path) -> bool:
    p=Path(model_path); backup=p.with_name(p.name+".previous")
    if not backup.exists(): return False
    os.replace(backup,p)
    backup_meta=Path(str(backup)+".meta.json")
    meta=p.with_suffix(p.suffix+".meta.json")
    if backup_meta.exists(): os.replace(backup_meta,meta)
    return True


def verify_artifact_signature(digest: str, signature: str) -> bool:
    signature = str(signature or "")
    public_pem = str(settings.model_signing_public_key or "")
    if public_pem and signature:
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            key = load_pem_public_key(public_pem.encode())
            if not isinstance(key, Ed25519PublicKey):
                return False
            padded = signature + "=" * (-len(signature) % 4)
            key.verify(base64.urlsafe_b64decode(padded.encode()), digest.encode())
            return True
        except Exception:
            return False
    # Legacy HMAC verification is kept only so already-deployed 3.10.44 artifacts can be
    # migrated/retrained; staging/production config now requires the Ed25519 public key.
    legacy = str(settings.model_signing_key or "")
    return bool(legacy and signature) and hmac.compare_digest(
        hmac.new(legacy.encode(), digest.encode(), hashlib.sha256).hexdigest(), signature
    )
