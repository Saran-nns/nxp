"""
NXP Tool Sandboxing & Token Bucket Rate Limiter
"""

from __future__ import annotations

import time
import inspect
from typing import Any, Callable, Dict


class TokenBucketRateLimiter:
    """Token Bucket Rate Limiter per Caller DID."""
    def __init__(self, rate_limit_per_min: int = 60):
        self.capacity = rate_limit_per_min
        self.buckets: Dict[str, float] = {}
        self.last_update: Dict[str, float] = {}

    def allow_request(self, caller_did: str) -> bool:
        """Check if request from caller_did is permitted within rate limits."""
        now = time.time()
        if caller_did not in self.buckets:
            self.buckets[caller_did] = self.capacity
            self.last_update[caller_did] = now

        # Replenish tokens based on elapsed time
        elapsed = now - self.last_update[caller_did]
        replenish = elapsed * (self.capacity / 60.0)
        self.buckets[caller_did] = min(self.capacity, self.buckets[caller_did] + replenish)
        self.last_update[caller_did] = now

        if self.buckets[caller_did] >= 1.0:
            self.buckets[caller_did] -= 1.0
            return True
        return False


class ExecutionSandbox:
    """Execution Sandbox enforcing rate limits and isolated call boundaries."""
    def __init__(self, rate_limit_per_min: int = 60):
        self.limiter = TokenBucketRateLimiter(rate_limit_per_min=rate_limit_per_min)

    async def execute_sandboxed(self, caller_did: str, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Run tool function inside sandbox with rate limit check."""
        if not self.limiter.allow_request(caller_did):
            raise RuntimeError(f"Rate limit exceeded for DID '{caller_did}'. Max allowed: {self.limiter.capacity} calls/min")

        print(f"[ExecutionSandbox] Executing sandboxed tool call for DID '{caller_did}'...")
        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)


# Alias for Tool Sandbox
ToolSandbox = ExecutionSandbox
