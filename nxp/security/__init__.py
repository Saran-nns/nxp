"""Security — authentication middleware for nxp agents."""

from nxp.security.auth import APIKeyAuth, require_api_key

__all__ = ["APIKeyAuth", "require_api_key"]
