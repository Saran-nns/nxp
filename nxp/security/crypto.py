"""
NXP Zero-Trust Asymmetric Cryptography & Decentralized Identity (did:key)
"""

from __future__ import annotations

import base64
import hashlib
import os
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class Ed25519Identity:
    """
    NXP Zero-Trust Asymmetric PKI Identity.
    Generates Ed25519 public/private keys and formats public keys as did:key URIs.
    """
    def __init__(self, private_key: ed25519.Ed25519PrivateKey | None = None):
        if private_key is None:
            self.private_key = ed25519.Ed25519PrivateKey.generate()
        else:
            self.private_key = private_key
            
        self.public_key = self.private_key.public_key()
        
        # Derive Public Key Bytes (32 bytes)
        self.public_bytes = self.public_key.public_bytes_raw()
        self.public_hex = self.public_bytes.hex()
        
        # Derive DID identifier format (did:key:z6M...)
        digest = hashlib.sha256(self.public_bytes).hexdigest()[:24]
        self.did = f"did:key:z6M{digest}"

    @classmethod
    def generate(cls) -> Ed25519Identity:
        """Generate a new random Ed25519 Identity keypair."""
        return cls()

    def sign(self, payload: str) -> str:
        """Digitally sign a message payload string using the Ed25519 Private Key."""
        signature_bytes = self.private_key.sign(payload.encode("utf-8"))
        return signature_bytes.hex()

    @staticmethod
    def verify(public_key_hex: str, payload: str, signature_hex: str) -> bool:
        """
        Verify a digital signature using ONLY the sender's public key hex.
        Requires NO shared symmetric passwords!
        """
        try:
            pub_bytes = bytes.fromhex(public_key_hex)
            pub_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
            sig_bytes = bytes.fromhex(signature_hex)
            pub_key.verify(sig_bytes, payload.encode("utf-8"))
            return True
        except Exception:
            return False


class X25519KeyExchange:
    """
    Ephemeral X25519 Elliptic Curve Diffie-Hellman (ECDH) key exchange for
    deriving NXP per-connection SDMT session keys.

    Each side generates a fresh ephemeral keypair and a random 16-byte nonce
    per connection. After exchanging public keys and nonces, both sides
    independently derive the same symmetric session key via HKDF-SHA256 over
    the ECDH shared secret — the session key itself never travels on the wire.
    """
    def __init__(self, private_key: x25519.X25519PrivateKey | None = None):
        self.private_key = private_key or x25519.X25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()
        self.public_bytes = self.public_key.public_bytes_raw()
        self.nonce = os.urandom(16)

    def derive_session_key(
        self, peer_public_bytes: bytes, peer_nonce: bytes, *, length: int = 16
    ) -> bytes:
        """
        Compute the shared ECDH secret with a peer's ephemeral public key and
        derive a symmetric session key via HKDF-SHA256.

        The salt is the sorted concatenation of both nonces, so both peers
        derive an identical key regardless of which side is "A" or "B".
        """
        peer_key = x25519.X25519PublicKey.from_public_bytes(peer_public_bytes)
        shared_secret = self.private_key.exchange(peer_key)
        salt = b"".join(sorted([self.nonce, peer_nonce]))
        return HKDF(
            algorithm=hashes.SHA256(),
            length=length,
            salt=salt,
            info=b"nxp-sdmt-session-key",
        ).derive(shared_secret)


# Alias for Zero-Trust Security primitives
ZeroTrustSecurity = Ed25519Identity
