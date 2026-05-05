"""
RSA key management for LTI 1.3.

Generates a keypair on first run and caches it. In production,
keys should be loaded from env vars or a secrets manager.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_private_key: str | None = None
_public_key: str | None = None
_kid: str = "finsight-tool-key-1"

KEYS_DIR = Path(__file__).parent.parent.parent / "keys"


def _generate_keys() -> tuple[str, str]:
    """Generate a new RSA keypair."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def get_tool_private_key() -> str:
    """Get the tool's RSA private key (PEM). Generates if not found."""
    global _private_key
    if _private_key:
        return _private_key

    from app.config import get_settings
    settings = get_settings()

    if settings.lti_private_key_file:
        p = Path(settings.lti_private_key_file)
        if p.exists():
            _private_key = p.read_text()
            logger.info("Loaded LTI private key from %s", p)
            return _private_key

    key_file = KEYS_DIR / "private.pem"
    pub_file = KEYS_DIR / "public.pem"

    if key_file.exists():
        _private_key = key_file.read_text()
        logger.info("Loaded LTI private key from %s", key_file)
        return _private_key

    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    priv, pub = _generate_keys()
    key_file.write_text(priv)
    pub_file.write_text(pub)
    _private_key = priv
    _public_key = pub
    logger.info("Generated new LTI RSA keypair in %s", KEYS_DIR)
    return _private_key


def get_tool_public_key() -> str:
    """Get the tool's RSA public key (PEM)."""
    global _public_key
    if _public_key:
        return _public_key

    get_tool_private_key()

    pub_file = KEYS_DIR / "public.pem"
    if pub_file.exists():
        _public_key = pub_file.read_text()
        return _public_key

    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives import serialization

    private = load_pem_private_key(get_tool_private_key().encode(), password=None)
    _public_key = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return _public_key


def get_tool_jwks() -> dict:
    """Return the tool's public key in JWKS format."""
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    import base64

    pub_pem = get_tool_public_key()
    pub_key = load_pem_public_key(pub_pem.encode())
    numbers = pub_key.public_numbers()

    def _int_to_base64url(n: int) -> str:
        byte_length = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()

    return {
        "keys": [{
            "kty": "RSA",
            "kid": _kid,
            "use": "sig",
            "alg": "RS256",
            "n": _int_to_base64url(numbers.n),
            "e": _int_to_base64url(numbers.e),
        }]
    }


def get_kid() -> str:
    return _kid
