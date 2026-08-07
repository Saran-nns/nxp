"""
Identity — Agent Trust & DID for the Internet of Agents.

Problem Solved
--------------
"Agent trust — Currently: None | Future: PKI / DID for agents"

Every nxp agent gets a cryptographic identity:
  - A unique DID (Decentralised Identifier): did:nxp:<name>:<fingerprint>
  - HMAC-SHA256 signed responses (tamper-proof)
  - Verifiable signature on every skill call response

Usage
-----
    from nxp import Agent
    from nxp import Identity

    agent = Agent(
        name="research-agent",
        description="...",
        identity=Identity(secret="my-32-char-signing-secret-key!!"),
    )

    # Every HTTP response now includes:
    #   X-Agent-DID:  did:nxp:research-agent:a3f8c1d2
    #   X-Agent-Sig:  <hmac-sha256 of response body>
    #   X-Agent-Ts:   <unix timestamp>
    #   X-Trace-ID:   <request trace id>

Verifying a response (client side):
    from nxp import Identity

    identity = Identity(secret="my-32-char-signing-secret-key!!")
    is_valid = identity.verify(response_body_json, response_headers["X-Agent-Sig"])
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Identity:
    """
    Cryptographic identity for a nxp agent.

    Provides:
      - Deterministic DID (did:nxp:<name>:<fingerprint>)
      - HMAC-SHA256 response signing
      - Signature verification for response integrity

    Args:
        secret: A secret key used for HMAC signing. Treat like a password —
                keep it private and use at least 32 characters.
    """

    secret: str
    agent_name: Optional[str] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if len(self.secret) < 16:
            raise ValueError(
                "Identity secret must be at least 16 characters long. "
                "Use a random string like: nxp keygen"
            )

    # ─── DID ─────────────────────────────────────────────────────────────────

    def did(self) -> str:
        """
        Return this agent's Decentralised Identifier (DID).

        Format: did:nxp:<agent_name>:<fingerprint>
        The fingerprint is a deterministic 16-char hex derived from name + secret.

        Example: "did:nxp:research-agent:a3f8c1d2e4b5f6a7"
        """
        raw = f"{self.agent_name or 'unknown'}:{self.secret}"
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
        name = (self.agent_name or "unknown").replace(" ", "-").lower()
        return f"did:nxp:{name}:{fingerprint}"

    def fingerprint(self) -> str:
        """Short 8-char fingerprint for display."""
        return self.did().split(":")[-1][:8]

    # ─── Signing ──────────────────────────────────────────────────────────────

    def sign(self, payload: str) -> str:
        """
        Compute an HMAC-SHA256 signature of the given payload string.

        Args:
            payload: The string to sign (typically JSON-serialized response body).

        Returns:
            Hex-encoded HMAC-SHA256 signature.
        """
        return hmac.new(
            self.secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify(self, payload: str, signature: str) -> bool:
        """
        Verify that a signature matches the payload.

        Uses constant-time comparison to prevent timing attacks.

        Args:
            payload:   The original payload string that was signed.
            signature: The HMAC-SHA256 hex string to verify.

        Returns:
            True if the signature is valid, False otherwise.
        """
        expected = self.sign(payload)
        return hmac.compare_digest(expected, signature)

    def sign_dict(self, data: Dict[str, Any]) -> str:
        """Sign a dict by serializing to canonical JSON first."""
        return self.sign(json.dumps(data, sort_keys=True, separators=(",", ":")))

    # ─── HTTP Response Headers ────────────────────────────────────────────────

    def response_headers(self, response_body: Dict[str, Any]) -> Dict[str, str]:
        """
        Generate identity HTTP headers to attach to every response.

        Returns a dict of headers:
          X-Agent-DID:  The agent's DID
          X-Agent-Sig:  HMAC-SHA256 signature of the response body
          X-Agent-Ts:   Unix timestamp (for replay attack prevention)
        """
        payload = json.dumps(response_body, sort_keys=True, separators=(",", ":"))
        return {
            "X-Agent-DID": self.did(),
            "X-Agent-Sig": self.sign(payload),
            "X-Agent-Ts": str(int(time.time())),
        }

    def __repr__(self) -> str:
        return f"Identity(did={self.did()!r})"
