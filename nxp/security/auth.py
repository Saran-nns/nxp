"""
Authentication middleware for nxp agents.

Provides:
  - APIKeyAuth: FastAPI dependency for Bearer token / API key validation
  - require_api_key: Simple decorator to protect individual routes

Usage
-----
    from nxp import Agent
    from nxp.security import APIKeyAuth

    auth = APIKeyAuth(keys=["sk-secret-key-1", "sk-secret-key-2"])
    agent = Agent(name="secure-agent", description="...")

    # Apply to the HTTP transport app after agent is set up
    # (Advanced: mount middleware manually if needed)

    # Client side:
    client = connect("http://localhost:8000", api_key="sk-secret-key-1")
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import List, Optional

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(auto_error=False)


class APIKeyAuth:
    """
    Simple Bearer-token / API key authentication dependency for FastAPI.

    Example
    -------
        from nxp.security import APIKeyAuth

        auth = APIKeyAuth(keys=["sk-my-key"])

        @app.post("/skills/{skill_id}", dependencies=[Depends(auth)])
        async def call_skill(...):
            ...
    """

    def __init__(self, keys: List[str], *, case_sensitive: bool = True) -> None:
        """
        Create an APIKeyAuth dependency.

        Args:
            keys: List of valid API keys (Bearer tokens).
            case_sensitive: If False, key comparison is case-insensitive.
        """
        if not keys:
            raise ValueError("APIKeyAuth requires at least one valid key.")
        self._keys = keys if case_sensitive else [k.lower() for k in keys]
        self._case_sensitive = case_sensitive

    async def __call__(
        self,
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
    ) -> str:
        """FastAPI dependency — validates the Bearer token in Authorization header."""
        token: Optional[str] = None

        if credentials and credentials.scheme.lower() == "bearer":
            token = credentials.credentials
        else:
            # Also accept x-api-key header as fallback
            token = request.headers.get("x-api-key")

        if not token:
            raise HTTPException(
                status_code=401,
                detail="Missing API key. Provide 'Authorization: Bearer <key>' header.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        compare_token = token if self._case_sensitive else token.lower()

        # Constant-time comparison to prevent timing attacks
        valid = any(
            hmac.compare_digest(compare_token, k) for k in self._keys
        )

        if not valid:
            raise HTTPException(
                status_code=403,
                detail="Invalid API key.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return token


def require_api_key(keys: List[str]) -> APIKeyAuth:
    """
    Factory shorthand for APIKeyAuth.

    Example:
        auth = require_api_key(["sk-my-key"])
    """
    return APIKeyAuth(keys=keys)


def generate_api_key(prefix: str = "nxp") -> str:
    """
    Generate a cryptographically secure API key.

    Returns a key in the format: ``nxp-<32-hex-chars>``

    Example:
        key = generate_api_key()
        # "nxp-a3f8c1d2e4b5f6a7b8c9d0e1f2a3b4c5"
    """
    token = secrets.token_hex(16)
    return f"{prefix}-{token}"
