#!/usr/bin/env python3
"""Offline-only migration helper. Never run this inside the Atlas API image.
Outputs the public account-level xpub for m/44'/195'/0'."""
import argparse
from bip_utils import Bip44, Bip44Coins

p=argparse.ArgumentParser()
p.add_argument('--seed-hex', required=True, help='Legacy 32-byte seed; use only on an offline trusted machine')
args=p.parse_args()
seed=bytes.fromhex(args.seed_hex.strip())
if len(seed)!=32:
    raise SystemExit('seed-hex must be exactly 32 bytes')
ctx=(Bip44.FromSeed(seed,Bip44Coins.TRON).Purpose().Coin().Account(0))
if ctx.IsPublicOnly():
    raise SystemExit('unexpected public-only account')
print(ctx.PublicKey().ToExtended())
