from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

private = Ed25519PrivateKey.generate()
public = private.public_key()
private_pem = private.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
public_pem = public.public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()
print("MODEL_SIGNING_PRIVATE_KEY<<EOF")
print(private_pem, end="")
print("EOF")
print("MODEL_SIGNING_PUBLIC_KEY<<EOF")
print(public_pem, end="")
print("EOF")
