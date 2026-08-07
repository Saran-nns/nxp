"""
HTTP Transport — A2A-compatible FastAPI server.

Endpoints (Core)
----------------
  GET  /.well-known/agent-card.json  — Agent Card (A2A discovery)
  GET  /health                       — Health check
  GET  /skills                       — List all skills
  POST /skills/{skill_id}            — Execute a skill (direct call)
  POST /tasks                        — Submit an async task
  GET  /tasks/{task_id}              — Poll task status
  DELETE /tasks/{task_id}            — Cancel a pending task

Endpoints (Infrastructure — v0.1)
----------------------------------
  GET  /identity                     — Agent DID and identity info
  GET  /observe/events               — Recent trace events
  GET  /observe/traces/{trace_id}    — Events for a specific trace
  GET  /observe/stats                — Per-skill call stats

Response Headers (when identity= is configured)
------------------------------------------------
  X-Agent-DID:   Agent's DID (did:nxp:name:fingerprint)
  X-Agent-Sig:   HMAC-SHA256 signature of response body
  X-Agent-Ts:    Unix timestamp
  X-Trace-ID:    Request trace ID (propagated from client or generated)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from nxp.transport.base import BaseTransport

if TYPE_CHECKING:
    from nxp.agent import Agent


# ─── Request / Response Models ──────────────────────────────────────────────────


class SkillCallRequest(BaseModel):
    """Body for POST /skills/{skill_id}"""

    kwargs: Dict[str, Any] = {}


class TaskSubmitRequest(BaseModel):
    """Body for POST /tasks"""

    skill_id: str
    kwargs: Dict[str, Any] = {}
    message: str = ""  # Optional natural-language task description


class TaskRecord(BaseModel):
    """A task record stored in memory."""

    task_id: str
    skill_id: str
    status: str  # submitted | working | completed | failed | canceled
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


# ─── HTTP Transport ─────────────────────────────────────────────────────────────


class HTTPTransport(BaseTransport):
    """
    A2A-compatible HTTP server built on FastAPI + Uvicorn.

    Serves the Agent Card at the standard well-known URL and exposes
    skill execution and async task delegation endpoints.
    """

    def __init__(self, agent: "Agent", host: str = "0.0.0.0", port: int = 8000) -> None:
        super().__init__(agent)
        self.host = host
        self.port = port
        self._tasks: Dict[str, TaskRecord] = {}
        self.app = self._build_app()

    def _build_app(self) -> FastAPI:
        agent = self.agent
        tasks = self._tasks

        app = FastAPI(
            title=agent.name,
            description=agent.description,
            version=agent.version,
            docs_url="/docs",
            redoc_url="/redoc",
        )

        # CORS — permissive for development; tighten in production
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # ── Discovery ─────────────────────────────────────────────────────────

        @app.get("/.well-known/agent-card.json", tags=["discovery"])
        async def agent_card(request: Request) -> JSONResponse:
            """A2A Agent Card — describes this agent's identity and skills."""
            base_url = str(request.base_url).rstrip("/")
            card = agent.get_card(base_url=base_url)
            return JSONResponse(card.model_dump(by_alias=False))

        @app.get("/health", tags=["meta"])
        async def health() -> Dict[str, Any]:
            """Health check endpoint."""
            return {
                "status": "ok",
                "agent": agent.name,
                "version": agent.version,
                "skills": len(agent._skills),
            }

        # ── Skills ────────────────────────────────────────────────────────────

        @app.get("/skills", tags=["skills"])
        async def list_skills() -> Dict[str, Any]:
            """List all skills registered on this agent."""
            return {
                "agent": agent.name,
                "skills": [
                    s.to_skill_definition().model_dump()
                    for s in agent._skills.values()
                ],
            }

        @app.get("/skills/{skill_id}", tags=["skills"])
        async def get_skill(skill_id: str) -> Dict[str, Any]:
            """Get metadata for a single skill."""
            if skill_id not in agent._skills:
                raise HTTPException(
                    status_code=404,
                    detail=f"Skill '{skill_id}' not found. "
                    f"Available: {list(agent._skills.keys())}",
                )
            return agent._skills[skill_id].to_skill_definition().model_dump()

        @app.post("/skills/{skill_id}", tags=["skills"])
        async def call_skill(skill_id: str, req: SkillCallRequest, request: Request) -> Dict[str, Any]:
            """
            Execute a skill and return the result synchronously.

            Trace ID is read from X-Trace-ID header if present, or a new one
            is generated. Propagate this ID to downstream agents for end-to-end tracing.
            """
            if skill_id not in agent._skills:
                raise HTTPException(
                    status_code=404,
                    detail=f"Skill '{skill_id}' not found. "
                    f"Available: {list(agent._skills.keys())}",
                )

            # ── Trace ID (from header or generate) ──────────────────────
            trace_id = request.headers.get("X-Trace-ID", "")
            if not trace_id and agent.observe:
                trace_id = agent.observe.new_trace_id()

            skill = agent._skills[skill_id]
            import time as _time
            start = _time.monotonic()
            result = None
            error_str = None

            try:
                result = await skill.execute(**req.kwargs)
            except TypeError as e:
                error_str = str(e)
                raise HTTPException(status_code=422, detail=f"Invalid arguments for '{skill_id}': {e}")
            except Exception as e:
                error_str = str(e)
                raise HTTPException(status_code=500, detail=f"Skill '{skill_id}' raised an error: {e}")
            finally:
                duration_ms = (_time.monotonic() - start) * 1000
                # ── Observability ───────────────────────────────────
                if agent.observe and trace_id:
                    agent.observe.record(
                        trace_id, agent.name, skill_id, "call_end",
                        duration_ms=duration_ms,
                        status="ok" if error_str is None else "error",
                        kwargs=req.kwargs,
                        error=error_str,
                    )

            body = {"skill_id": skill_id, "status": "completed", "result": result}

            # ── Identity: sign the response ──────────────────────────
            headers: Dict[str, str] = {}
            if agent.identity:
                headers.update(agent.identity.response_headers(body))
            if trace_id:
                headers["X-Trace-ID"] = trace_id

            return JSONResponse(body, headers=headers)

        # ── Tasks (Async) ─────────────────────────────────────────────────────

        @app.post("/tasks", status_code=202, tags=["tasks"])
        async def submit_task(req: TaskSubmitRequest) -> Dict[str, Any]:
            """
            Submit a skill as an async background task.

            Returns immediately with a task_id. Poll GET /tasks/{task_id}
            to check status and retrieve the result.

            Task lifecycle: submitted → working → completed | failed | canceled
            """
            task_id = str(uuid.uuid4())
            now = _now()

            if req.skill_id not in agent._skills:
                return {
                    "task_id": task_id,
                    "status": "failed",
                    "error": f"Skill '{req.skill_id}' not found.",
                    "created_at": now,
                    "updated_at": now,
                }

            record = TaskRecord(
                task_id=task_id,
                skill_id=req.skill_id,
                status="submitted",
                created_at=now,
                updated_at=now,
            )
            tasks[task_id] = record

            # Fire and forget — updates record in place
            asyncio.create_task(self._run_task(task_id, req.skill_id, req.kwargs))

            return record.model_dump()

        @app.get("/tasks/{task_id}", tags=["tasks"])
        async def get_task(task_id: str) -> Dict[str, Any]:
            """Poll a task's current status and result."""
            if task_id not in tasks:
                raise HTTPException(
                    status_code=404,
                    detail=f"Task '{task_id}' not found.",
                )
            return tasks[task_id].model_dump()

        @app.delete("/tasks/{task_id}", tags=["tasks"])
        async def cancel_task(task_id: str) -> Dict[str, Any]:
            """Cancel a pending task (only effective before it starts working)."""
            if task_id not in tasks:
                raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
            task = tasks[task_id]
            if task.status == "submitted":
                task.status = "canceled"
                task.updated_at = _now()
            return task.model_dump()

        # ── Identity ──────────────────────────────────────────────────────────

        @app.get("/identity", tags=["infrastructure"])
        async def identity_info() -> Dict[str, Any]:
            """Agent DID and identity information."""
            if not agent.identity:
                raise HTTPException(
                    status_code=404,
                    detail="Identity not configured. Pass identity=Identity(secret=...) to Agent()."
                )
            return {
                "did": agent.identity.did(),
                "fingerprint": agent.identity.fingerprint(),
                "agent": agent.name,
                "version": agent.version,
                "signing": "HMAC-SHA256",
                "headers": ["X-Agent-DID", "X-Agent-Sig", "X-Agent-Ts", "X-Trace-ID"],
            }

        # ── Observability ─────────────────────────────────────────────────────

        @app.get("/observe/events", tags=["infrastructure"])
        async def observe_events(n: int = 50) -> Dict[str, Any]:
            """Recent trace events (last N calls across all skills)."""
            if not agent.observe:
                raise HTTPException(
                    status_code=404,
                    detail="Observability not configured. Pass observe=Observability() to Agent()."
                )
            return {
                "agent": agent.name,
                "events": agent.observe.recent_events(n),
                "total": len(agent.observe._events),
            }

        @app.get("/observe/traces/{trace_id}", tags=["infrastructure"])
        async def observe_trace(trace_id: str) -> Dict[str, Any]:
            """All events for a specific trace ID — follow a request across agents."""
            if not agent.observe:
                raise HTTPException(status_code=404, detail="Observability not configured.")
            events = agent.observe.trace_events(trace_id)
            return {"trace_id": trace_id, "events": events, "count": len(events)}

        @app.get("/observe/stats", tags=["infrastructure"])
        async def observe_stats() -> Dict[str, Any]:
            """Per-skill call counts and average durations."""
            if not agent.observe:
                raise HTTPException(status_code=404, detail="Observability not configured.")
            return {"agent": agent.name, "skills": agent.observe.skill_stats()}



            return {"agent": agent.name, "skills": agent.observe.skill_stats()}

        return app

    # ─── Task Runner ─────────────────────────────────────────────────────────────

    async def _run_task(
        self, task_id: str, skill_id: str, kwargs: Dict[str, Any]
    ) -> None:
        """Execute a task in the background, update its record, persist if runtime is set."""
        agent = self.agent
        tasks = self._tasks

        # Get or create an in-memory record
        if task_id not in tasks:
            now = _now()
            tasks[task_id] = TaskRecord(
                task_id=task_id,
                skill_id=skill_id,
                status="submitted",
                created_at=now,
                updated_at=now,
            )

        task = tasks[task_id]
        if task.status == "canceled":
            return

        task.status = "working"
        task.updated_at = _now()

        # ── Observability: trace task start ─────────────────────
        trace_id = ""
        if agent.observe:
            trace_id = agent.observe.new_trace_id()

        import time as _time
        start = _time.monotonic()
        error_str = None

        try:
            skill = agent._skills[skill_id]
            result = await skill.execute(**kwargs)
            task.status = "completed"
            task.result = result
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            error_str = str(exc)
        finally:
            task.updated_at = _now()
            duration_ms = (_time.monotonic() - start) * 1000

            # ── Observability: log task completion ────────────────
            if agent.observe and trace_id:
                agent.observe.record(
                    trace_id, agent.name, skill_id, "task_complete",
                    duration_ms=duration_ms,
                    status="ok" if error_str is None else "error",
                    kwargs=kwargs, error=error_str,
                    task_id=task_id,
                )

    # ─── Serve ───────────────────────────────────────────────────────────────────

    async def serve(self) -> None:
        """Start the Uvicorn server."""
        from rich.console import Console
        from rich.panel import Panel

        console = Console()

        # Build status lines
        infra_lines = []
        if self.agent.identity:
            infra_lines.append(f"[dim]DID:[/dim]      [magenta]{self.agent.identity.did()}[/magenta]")
        if self.agent.observe:
            infra_lines.append(f"[dim]Observe:[/dim]  [cyan]http://{self.host}:{self.port}/observe/events[/cyan]")
        if self.agent.registry:
            infra_lines.append(f"[dim]Registry:[/dim] [cyan]{self.agent.registry.url}[/cyan]")

        infra_str = ("\n" + "\n".join(infra_lines)) if infra_lines else ""

        console.print(
            Panel.fit(
                f"[bold green] {self.agent.name}[/bold green] "
                f"[dim]v{self.agent.version}[/dim]\n"
                f"[dim]Skills:[/dim]  [cyan]{', '.join(self.agent.skill_ids) or 'none'}[/cyan]\n"
                f"[dim]Endpoint:[/dim] [cyan]http://{self.host}:{self.port}[/cyan]\n"
                f"[dim]Docs:[/dim]     [cyan]http://{self.host}:{self.port}/docs[/cyan]\n"
                f"[dim]Card:[/dim]     [cyan]http://{self.host}:{self.port}/.well-known/agent-card.json[/cyan]"
                + infra_str,
                title="[bold] Cognitive Agent Tool[/bold]",
                border_style="green",
            )
        )

        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        await server.serve()


# ─── Helpers ─────────────────────────────────────────────────────────────────────


def _now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
