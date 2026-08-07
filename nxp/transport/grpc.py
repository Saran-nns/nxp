"""
gRPC Transport — High-performance async gRPC server.

Exposes agent skills via a typed gRPC service defined in agent.proto.
Supports unary execution, automatic exception mapping, and observability tracing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Dict

import grpc
from nxp.transport.base import BaseTransport
from nxp.transport import agent_pb2, agent_pb2_grpc

if TYPE_CHECKING:
    from nxp.core.agent import Agent

logger = logging.getLogger("nxp.transport.grpc")


class AgentServiceServicer(agent_pb2_grpc.AgentServiceServicer):
    """gRPC servicer mapping requests to nxp agent skills."""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def Execute(
        self, request: agent_pb2.ExecuteRequest, context: grpc.aio.ServicerContext
    ) -> agent_pb2.ExecuteResponse:
        skill_id = request.skill_id
        trace_id = request.trace_id

        if skill_id not in self.agent._skills:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Skill '{skill_id}' not found.")
            return agent_pb2.ExecuteResponse(error=f"Skill '{skill_id}' not found.")

        # Parse arguments
        try:
            kwargs = json.loads(request.kwargs_json) if request.kwargs_json else {}
        except json.JSONDecodeError as exc:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"Invalid JSON kwargs: {exc}")
            return agent_pb2.ExecuteResponse(error=f"Invalid JSON kwargs: {exc}")

        # Start trace tracking
        if not trace_id and self.agent.observe:
            trace_id = self.agent.observe.new_trace_id()

        skill = self.agent._skills[skill_id]
        import time as _time
        start = _time.monotonic()
        error_str = None
        result = None

        try:
            result = await skill.execute(**kwargs)
        except TypeError as exc:
            error_str = str(exc)
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(exc))
            return agent_pb2.ExecuteResponse(error=str(exc))
        except Exception as exc:
            error_str = str(exc)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
            return agent_pb2.ExecuteResponse(error=str(exc))
        finally:
            duration_ms = (_time.monotonic() - start) * 1000
            if self.agent.observe and trace_id:
                self.agent.observe.record(
                    trace_id,
                    self.agent.name,
                    skill_id,
                    "call_end",
                    duration_ms=duration_ms,
                    status="ok" if error_str is None else "error",
                    kwargs=kwargs,
                    error=error_str,
                )

        # Serialize result
        try:
            result_json = json.dumps(result)
        except Exception as exc:
            result_json = json.dumps(str(result))

        return agent_pb2.ExecuteResponse(result_json=result_json)


class GRPCTransport(BaseTransport):
    """
    gRPC transport server.

    Serves the AgentService on the specified port.
    """

    def __init__(self, agent: Agent, host: str = "0.0.0.0", port: int = 50051) -> None:
        super().__init__(agent)
        self.host = host
        self.port = port
        self.server = None

    async def serve(self) -> None:
        """Start the gRPC server."""
        from rich.console import Console
        from rich.panel import Panel

        self.server = grpc.aio.server()
        agent_pb2_grpc.add_AgentServiceServicer_to_server(
            AgentServiceServicer(self.agent), self.server
        )

        bind_addr = f"{self.host}:{self.port}"
        self.server.add_insecure_port(bind_addr)

        console = Console()
        console.print(
            Panel.fit(
                f"[bold green] {self.agent.name}[/bold green] (gRPC transport)\n"
                f"[dim]Skills:[/dim]  [cyan]{', '.join(self.agent.skill_ids) or 'none'}[/cyan]\n"
                f"[dim]Endpoint:[/dim] [cyan]grpc://{self.host}:{self.port}[/cyan]",
                title="[bold] Cognitive Agent Tool (gRPC)[/bold]",
                border_style="green",
            )
        )

        await self.server.start()
        try:
            await self.server.wait_for_termination()
        except asyncio.CancelledError:
            await self.server.stop(grace=1.0)
