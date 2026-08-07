"""
Observability — Real-time tracing and monitoring for multi-agent systems.

Problem Solved
--------------
"Multi-agent debugging — Currently: Almost impossible | Future: Agent observability platforms"

Without this: when something breaks in a 10-agent pipeline, you have no idea where.
With this:    every call gets a trace ID, duration, status, and structured log entry.
              Trace IDs propagate across agents so you can follow a request end-to-end.

Usage
-----
    from nxp import Agent
    from nxp import Observability

    agent = Agent(
        name="research-agent",
        description="...",
        observe=Observability(trace=True, log_level="INFO"),
    )

    # Every skill call now logs:
    #    [a3f8c1d2] research-agent.search_web (142.3ms)
    #    [b4c2d3e1] research-agent.call_llm (32.1ms) ERROR: Rate limit exceeded

    # Live event stream: GET /observe/events
    # Live trace by ID:  GET /observe/traces/{trace_id}
    # Budget dashboard:  GET /observe/budget

    # Cross-agent tracing (propagate trace ID):
    researcher = connect("http://researcher:8000")
    result = await researcher.call("search_web", query="AI", _trace_id="a3f8c1d2")
    # The remote agent will log with the SAME trace ID
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ─── Trace Event ─────────────────────────────────────────────────────────────


@dataclass
class TraceEvent:
    """A single observable event in an agent's lifecycle."""

    trace_id: str
    agent_name: str
    skill_id: str
    event: str              # call_start | call_end | call_error | task_submit | task_complete
    timestamp: str
    duration_ms: Optional[float] = None
    status: str = "ok"      # ok | error | budget_exceeded
    kwargs_summary: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "agent": self.agent_name,
            "skill": self.skill_id,
            "event": self.event,
            "ts": self.timestamp,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "kwargs": self.kwargs_summary,
            "error": self.error,
            **self.metadata,
        }


# ─── Observability ────────────────────────────────────────────────────────────


@dataclass
class Observability:
    """
    Structured tracing and observability for nxp agents.

    Features:
      - Unique trace IDs per request (propagatable across agents)
      - Structured log entries for every skill call
      - In-memory event ring buffer (queryable via /observe/events)
      - Real-time console output with color-coded status
      - Duration tracking for performance monitoring

    Args:
        trace:          Enable trace ID generation and propagation (default True).
        log_level:      Python logging level: "DEBUG", "INFO", "WARNING" (default "INFO").
        log_file:       Optional file path for structured JSON logs.
        max_events:     Maximum events to keep in memory ring buffer (default 500).
    """

    trace: bool = True
    log_level: str = "INFO"
    log_file: Optional[str] = None
    max_events: int = 500

    def __post_init__(self) -> None:
        self._events: List[TraceEvent] = []
        self._logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger("nxp.observe")
        logger.setLevel(getattr(logging, self.log_level.upper(), logging.INFO))
        logger.propagate = False

        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s | nxp | %(message)s", datefmt="%H:%M:%S")
            )
            logger.addHandler(handler)

            if self.log_file:
                file_handler = logging.FileHandler(self.log_file)
                file_handler.setFormatter(
                    logging.Formatter('{"ts":"%(asctime)s","msg":"%(message)s"}')
                )
                logger.addHandler(file_handler)

        return logger

    # ─── Trace IDs ────────────────────────────────────────────────────────────

    def new_trace_id(self) -> str:
        """Generate a new short trace ID (8 chars, human-readable)."""
        return uuid.uuid4().hex[:8]

    # ─── Event Recording ─────────────────────────────────────────────────────

    def record(
        self,
        trace_id: str,
        agent_name: str,
        skill_id: str,
        event: str,
        *,
        duration_ms: Optional[float] = None,
        status: str = "ok",
        kwargs: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        **metadata: Any,
    ) -> TraceEvent:
        """
        Record an observable event and emit a structured log line.

        Returns the TraceEvent for further use.
        """
        # Summarize kwargs (truncate long values)
        kwargs_summary: Optional[str] = None
        if kwargs:
            parts = []
            for k, v in list(kwargs.items())[:3]:  # Max 3 params in summary
                v_str = str(v)
                if len(v_str) > 30:
                    v_str = v_str[:27] + "..."
                parts.append(f"{k}={v_str!r}")
            kwargs_summary = ", ".join(parts)
            if len(kwargs) > 3:
                kwargs_summary += f", +{len(kwargs)-3} more"

        evt = TraceEvent(
            trace_id=trace_id,
            agent_name=agent_name,
            skill_id=skill_id,
            event=event,
            timestamp=_now(),
            duration_ms=round(duration_ms, 2) if duration_ms else None,
            status=status,
            kwargs_summary=kwargs_summary,
            error=error,
            metadata=metadata,
        )

        # Ring buffer
        self._events.append(evt)
        if len(self._events) > self.max_events:
            self._events.pop(0)

        # Structured log line
        self._emit_log(evt)
        return evt

    def _emit_log(self, evt: TraceEvent) -> None:
        """Emit a structured log line for an event."""
        icon = "" if evt.status == "ok" else ("" if evt.status == "budget_exceeded" else "")
        msg = f"{icon} [{evt.trace_id}] {evt.agent_name}.{evt.skill_id}"
        if evt.duration_ms:
            msg += f" ({evt.duration_ms:.1f}ms)"
        if evt.kwargs_summary:
            msg += f" | {evt.kwargs_summary}"
        if evt.error:
            msg += f" | ERROR: {evt.error}"

        if evt.status == "ok":
            self._logger.info(msg)
        elif evt.status == "budget_exceeded":
            self._logger.warning(msg)
        else:
            self._logger.error(msg)

    # ─── Queries ─────────────────────────────────────────────────────────────

    def recent_events(self, n: int = 50) -> List[Dict[str, Any]]:
        """Return the N most recent events as dicts."""
        return [e.to_dict() for e in self._events[-n:]]

    def trace_events(self, trace_id: str) -> List[Dict[str, Any]]:
        """Return all events for a specific trace ID (cross-agent timeline)."""
        return [e.to_dict() for e in self._events if e.trace_id == trace_id]

    def skill_stats(self) -> Dict[str, Any]:
        """Return per-skill call counts and average durations."""
        stats: Dict[str, Dict[str, Any]] = {}
        for evt in self._events:
            s = stats.setdefault(
                evt.skill_id,
                {"calls": 0, "errors": 0, "total_ms": 0.0, "avg_ms": 0.0},
            )
            s["calls"] += 1
            if evt.status != "ok":
                s["errors"] += 1
            if evt.duration_ms:
                s["total_ms"] += evt.duration_ms

        for s in stats.values():
            if s["calls"]:
                s["avg_ms"] = round(s["total_ms"] / s["calls"], 2)
            del s["total_ms"]

        return stats

    def __repr__(self) -> str:
        return (
            f"Observability(trace={self.trace}, "
            f"events={len(self._events)}/{self.max_events})"
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
