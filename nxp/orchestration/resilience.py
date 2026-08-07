"""
NXP Circuit Breaker — client-side resilience primitive.

Protects a caller (and a struggling remote node) from being hammered by
repeated failing calls: once the error rate crosses a threshold, further
calls fail fast (no network round-trip) until a cooldown elapses, at which
point a small number of trial calls probe whether the node has recovered.
"""

from __future__ import annotations

import time
from collections import deque
from enum import Enum
from typing import Deque, Optional


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # normal operation, calls pass through
    OPEN = "OPEN"            # tripped: calls rejected immediately
    HALF_OPEN = "HALF_OPEN"  # cooldown elapsed: trial probes allowed


class CircuitOpenError(RuntimeError):
    """Raised by CircuitBreaker.allow_request() callers when the circuit is OPEN."""


class CircuitBreaker:
    """
    Real Circuit Breaker Finite State Machine.

    CLOSED: calls pass through; outcomes are tracked in a sliding window of
      the last `window` calls. Once at least `min_calls` samples exist, if
      the error rate exceeds `error_threshold` the circuit trips to OPEN.
    OPEN: `allow_request()` returns False immediately — no network attempt
      is made — until `cooldown_seconds` has elapsed since the trip, at
      which point the circuit moves to HALF_OPEN.
    HALF_OPEN: trial calls are allowed through one at a time.
      `half_open_success_threshold` consecutive successes closes the
      circuit and resets the window; a single failure trips it back to OPEN.
    """

    __slots__ = (
        "error_threshold", "window", "min_calls", "cooldown_seconds",
        "half_open_success_threshold", "_state", "_outcomes", "_opened_at",
        "_half_open_successes",
    )

    def __init__(
        self,
        error_threshold: float = 0.5,
        window: int = 10,
        min_calls: int = 3,
        cooldown_seconds: float = 1.0,
        half_open_success_threshold: int = 3,
    ):
        self.error_threshold = error_threshold
        self.window = window
        self.min_calls = min_calls
        self.cooldown_seconds = cooldown_seconds
        self.half_open_success_threshold = half_open_success_threshold

        self._state = CircuitState.CLOSED
        self._outcomes: Deque[bool] = deque(maxlen=window)  # True = success
        self._opened_at: Optional[float] = None
        self._half_open_successes = 0

    @property
    def state(self) -> CircuitState:
        """Current state, auto-advancing OPEN -> HALF_OPEN once cooldown has elapsed."""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_successes = 0
        return self._state

    def allow_request(self) -> bool:
        """Return True if a call should be attempted right now."""
        return self.state != CircuitState.OPEN

    def record_success(self) -> None:
        """Record a successful call outcome."""
        if self.state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self.half_open_success_threshold:
                self._close()
            return
        self._outcomes.append(True)

    def record_failure(self) -> None:
        """Record a failed call outcome, tripping the circuit if warranted."""
        if self.state == CircuitState.HALF_OPEN:
            self._open()
            return
        self._outcomes.append(False)
        if len(self._outcomes) >= self.min_calls:
            error_rate = 1.0 - (sum(self._outcomes) / len(self._outcomes))
            if error_rate > self.error_threshold:
                self._open()

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()

    def _close(self) -> None:
        self._state = CircuitState.CLOSED
        self._outcomes.clear()
        self._opened_at = None
        self._half_open_successes = 0
