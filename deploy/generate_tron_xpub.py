#!/usr/bin/env python3
"""Offline helper: derive the public TRON BIP44 account xpub from a seed.

Run this on a disconnected/offline machine. The API must receive only the resulting
account-level public key; the seed/private material must never enter Cloud Run or the
runtime Secret Manager configuration.
"""
from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from bip_utils import Bip44, Bip44Coins


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-hex", help="Existing 32-byte hex seed; omit to generate one offline")
    parser.add_argument("--seed-out", help="Write generated/existing seed to this local file with mode 0600")
    args = parser.parse_args()

    seed_hex = (args.seed_hex or "").strip().lower()
    if seed_hex:
        if len(seed_hex) != 64:
            raise SystemExit("--seed-hex must be exactly 32 bytes / 64 hex characters")
        try:
            seed = bytes.fromhex(seed_hex)
        except ValueError as exc:
            raise SystemExit("--seed-hex must contain hexadecimal characters only") from exc
    else:
        seed = secrets.token_bytes(32)
        seed_hex = seed.hex()

    ctx = Bip44.FromSeed(seed, Bip44Coins.TRON)
    account = ctx.Purpose().Coin().Account(0)
    xpub = account.PublicKey().RawCompressed().ToHex()  # raw key for diagnostics only
    account_xpub = account.PublicKey().ToExtended()

    if args.seed_out:
        path = Path(args.seed_out).expanduser().resolve()
        path.write_text(seed_hex + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        print(f"Seed written to: {path}")
    elif not args.seed_hex:
        print("GENERATED_SEED_HEX=" + seed_hex)

    print("TRON_ACCOUNT_XPUB=" + account_xpub)
    print("Account path: m/44'/195'/0'")
    print("Verify: store only TRON_ACCOUNT_XPUB in AtlasRisk runtime configuration.")
    print("Raw public-key diagnostic (not the xpub): " + xpub)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
