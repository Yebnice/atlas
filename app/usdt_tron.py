from __future__ import annotations

from typing import Any

try:
    from bip_utils import Bip44, Bip44Changes, Bip44Coins
except ImportError:
    Bip44 = None
    Bip44Changes = None
    Bip44Coins = None

STANDARD_PATH_PREFIX = "m/44'/195'/0'/0/"
LEGACY_PATH_PREFIX = "m/44'/195'/"


def require_tron_wallet_backend() -> Any:
    if Bip44 is None or Bip44Coins is None or Bip44Changes is None:
        raise RuntimeError("bip-utils is required for TRON address derivation; install bip-utils==2.12.2")
    return Bip44


def derive_usdt_tron_address_from_xpub(account_xpub: str, address_index: int) -> str:
    """Derive a TRON deposit address from an account-level public key only.

    The xpub must represent m/44'/195'/0'. From there only non-hardened
    change/address children are derived, so the server never receives the seed.
    """
    if address_index < 0 or address_index >= 2**31:
        raise ValueError("address_index must be between 0 and 2^31-1")
    xpub = str(account_xpub or '').strip()
    if not xpub:
        raise ValueError("USDT_TRON_ACCOUNT_XPUB is not configured")
    require_tron_wallet_backend()
    try:
        ctx = Bip44.FromExtendedKey(xpub, Bip44Coins.TRON)
        # Account-level xpub is depth 3. These are public derivations only.
        return ctx.Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_index).PublicKey().ToAddress()
    except Exception as exc:
        raise ValueError("USDT_TRON_ACCOUNT_XPUB is invalid or not an account-level TRON extended public key") from exc


def validate_tron_account_xpub(account_xpub: str) -> bool:
    try:
        xpub = str(account_xpub or '').strip()
        if not xpub:
            return False
        require_tron_wallet_backend()
        ctx = Bip44.FromExtendedKey(xpub, Bip44Coins.TRON)
        # BIP44 account level is depth 3; public-only key must not expose private material.
        return bool(ctx.IsPublicOnly() and int(ctx.Bip32Object().Depth().ToInt()) == 3)
    except Exception:
        return False


def derive_usdt_tron_address(seed_hex: str, customer_number: int) -> str:
    """Deprecated: intentionally disabled in the API runtime.

    Kept as a compatibility symbol so old offline tooling fails closed rather than
    silently reintroducing master-seed custody into the application process.
    """
    raise RuntimeError("Master-seed TRON derivation is disabled in AtlasRisk API; use account-level xpub derivation")


def derive_usdt_tron_address_legacy(seed_hex: str, customer_number: int) -> str:
    raise RuntimeError("Legacy TRON seed derivation is disabled in AtlasRisk API; use offline recovery tooling")
