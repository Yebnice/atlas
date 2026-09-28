#!/usr/bin/env python3
"""Sign a withdrawal proposal digest locally. The private key never leaves this machine.

Usage:
  python scripts/sign_withdrawal.py --digest <sha256-digest> --private-key ~/.keys/withdrawal_ed25519.pem
"""
import argparse, base64
from pathlib import Path
from cryptography.hazmat.primitives import serialization

p=argparse.ArgumentParser()
p.add_argument('--digest', required=True)
p.add_argument('--private-key', required=True)
a=p.parse_args()
key=serialization.load_pem_private_key(Path(a.private_key).read_bytes(), password=None)
sig=key.sign(a.digest.encode())
print(base64.b64encode(sig).decode())
