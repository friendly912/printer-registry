"""Signing key management for the registration terminal (write) and the
verification terminal (read-only, public key only).

Phase 0 stores keys as local PEM files. In Phase 1+ the private key moves
into a TPM/USB security key and this module's write path is replaced by a
call into that hardware instead of touching a key file directly.
"""
from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey, EllipticCurvePublicKey

CURVE = ec.SECP256R1()


def generate_keypair(private_key_path: Path, public_key_path: Path) -> None:
    """Generate a new ECDSA (P-256) keypair for a registration terminal."""
    private_key = ec.generate_private_key(CURVE)
    private_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def load_private_key(path: Path) -> EllipticCurvePrivateKey:
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def load_public_key(path: Path) -> EllipticCurvePublicKey:
    return serialization.load_pem_public_key(path.read_bytes())


def sign(private_key: EllipticCurvePrivateKey, payload: bytes) -> bytes:
    return private_key.sign(payload, ec.ECDSA(hashes.SHA256()))


def verify(public_key: EllipticCurvePublicKey, payload: bytes, signature: bytes) -> bool:
    try:
        public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False
