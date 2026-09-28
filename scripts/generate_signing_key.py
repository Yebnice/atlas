#!/usr/bin/env python3
"""Generate an Ed25519 keypair for local withdrawal signing.
The private key must stay on the operator workstation."""
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import argparse
p=argparse.ArgumentParser(); p.add_argument('--out', default='withdrawal_signer.pem'); a=p.parse_args()
key=Ed25519PrivateKey.generate()
Path(a.out).write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
Path(a.out+'.pub').write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
print('Private:', a.out); print('Public:', a.out+'.pub')
