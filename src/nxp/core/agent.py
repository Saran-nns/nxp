"""
Core Agent class — the heart of Cognitive Agent Tool.

Usage
-----
    from nxp import Agent
    from nxp.security.identity import Identity
    from nxp.orchestration.observe import Observability
    from nxp.core.registry import Registry

    agent = Agent(
        name="my-agent",
        description="Does useful things",
        version="1.0.0",

        #  Agent Trust — PKI/DID identity
        identity=Identity(secret="my-secret-signing-key"),

        #  Observability — trace every call
        observe=Observability(trace=True),

        #  Registry — auto-register for discovery
        registry=Registry(url="http://localhost:9999"),
    )

    @agent.skill(tags=["demo"])
    def greet(name: str) -> str:
        \"\"\"Greet someone by name.\"\"\"
        return f"Hello, {name}!"

    agent.run(port=8000)
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from nxp.core.card import AgentCard, AgentCapabilities, Provider
from nxp.core.skill import RegisteredSkill

if TYPE_CHECKING:
    from nxp.security.identity import Identity
    from nxp.orchestration.observe import Observability
    from nxp.core.registry import Registry


class Agent:
    """
    An AI agent that exposes skills via multiple transport protocols.

    Supported transports:
      - ``http``  (default) — A2A-compatible FastAPI server
      - ``mcp``             — MCP stdio JSON-RPC server (works with Claude, Cursor)

    Example
    -------
        agent = Agent(name="calculator", description="Does math")

        @agent.skill(tags=["math"])
        def add(a: float, b: float) -> float:
            \"\"\"Add two numbers.\"\"\"
            return a + b

        agent.run()
    """

    def __init__(
        self,
        name: str,
        description: str,
        version: str = "0.1.0",
        provider: Optional[Dict[str, str]] = None,
        tags: Optional[List[str]] = None,
        # ── v0.1 Infrastructure Layers ────────────────────────────────────
        identity: Optional["Identity"] = None,
        observe: Optional["Observability"] = None,
        registry: Optional["Registry"] = None,
    ) -> None:
        """
        Create a new Agent.

        Args:
            name:        Human-readable agent name.
            description: LLM-facing description of what this agent does.
            version:     Semantic version string, e.g. "1.0.0".
            provider:    Optional dict with 'name', 'url', 'support_contact'.
            tags:        Optional categorization tags for this agent.

            identity:    Agent identity for trust & DID signing.
                         → solves: "Agent trust — None → PKI/DID"
            observe:     Structured tracing and observability.
                         → solves: "Multi-agent debugging — almost impossible → observability platforms"
            registry:    Registry client for auto-registration and discovery.
                         → solves: "Agent marketplaces — nascent → verified agent registries"
        """
        self.name = name
        self.description = description
        self.version = version
        self.provider = provider
        self.tags: List[str] = tags or []

        # Infrastructure layers
        self.identity = identity
        self.observe = observe
        self.registry = registry

        # Wire agent name into identity (needed for DID generation)
        if identity:
            identity.agent_name = name

        self._skills: Dict[str, RegisteredSkill] = {}
        self._base_url: str = ""

    # ─── Skill Registration ─────────────────────────────────────────────────────

    def skill(
        self,
        *,
        skill_id: Optional[str] = None,
        name: Optional[str] = None,
        tags: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
        input_modes: Optional[List[str]] = None,
        output_modes: Optional[List[str]] = None,
        transports: Optional[List[str]] = None,
    ) -> Callable:
        """Decorator to register a function as a reasoning skill on this agent."""
        return self._register_capability(
            skill_id=skill_id, name=name, tags=tags, examples=examples,
            input_modes=input_modes, output_modes=output_modes, transports=transports,
            type="skill"
        )

    def tool(
        self,
        *,
        tool_id: Optional[str] = None,
        name: Optional[str] = None,
        tags: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
        input_modes: Optional[List[str]] = None,
        output_modes: Optional[List[str]] = None,
        transports: Optional[List[str]] = None,
    ) -> Callable:
        """Decorator to register a function as a deterministic tool on this agent."""
        return self._register_capability(
            skill_id=tool_id, name=name, tags=tags, examples=examples,
            input_modes=input_modes, output_modes=output_modes, transports=transports,
            type="tool"
        )

    def procedure(
        self,
        *,
        procedure_id: Optional[str] = None,
        name: Optional[str] = None,
        tags: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
        input_modes: Optional[List[str]] = None,
        output_modes: Optional[List[str]] = None,
        transports: Optional[List[str]] = None,
    ) -> Callable:
        """Decorator to register a function as a multi-step procedure on this agent."""
        return self._register_capability(
            skill_id=procedure_id, name=name, tags=tags, examples=examples,
            input_modes=input_modes, output_modes=output_modes, transports=transports,
            type="procedure"
        )

    def _register_capability(
        self,
        *,
        skill_id: Optional[str] = None,
        name: Optional[str] = None,
        tags: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
        input_modes: Optional[List[str]] = None,
        output_modes: Optional[List[str]] = None,
        transports: Optional[List[str]] = None,
        type: str = "skill",
    ) -> Callable:
        def decorator(func: Callable) -> Callable:
            _id = skill_id or func.__name__
            _name = name or func.__name__.replace("_", " ").title()
            _desc = inspect.getdoc(func) or _name

            registered = RegisteredSkill(
                func=func,
                skill_id=_id,
                name=_name,
                description=_desc,
                tags=tags or [],
                examples=examples or [],
                input_modes=input_modes or ["text/plain", "application/json"],
                output_modes=output_modes or ["text/plain", "application/json"],
                transports=transports,
                type=type,
            )
            self._skills[_id] = registered
            return func

        return decorator

    # ─── Agent Card ─────────────────────────────────────────────────────────────

    def get_card(self, base_url: str = "") -> AgentCard:
        """
        Generate an A2A-compatible Agent Card from registered skills.

        Args:
            base_url: The public base URL of the agent (used as the endpoint URL).

        Returns:
            AgentCard ready to be serialized and served.
        """
        from nxp import __version__ as cat_version

        url = base_url or self._base_url or "http://localhost:8000"

        provider_obj: Optional[Provider] = None
        if self.provider:
            provider_obj = Provider(
                name=self.provider.get("name", ""),
                url=self.provider.get("url"),
                support_contact=self.provider.get("support_contact"),
            )

        return AgentCard(
            name=self.name,
            description=self.description,
            version=self.version,
            url=url,
            capabilities=AgentCapabilities(streaming=True),
            skills=[s.to_skill_definition() for s in self._skills.values()],
            provider=provider_obj,
            cat_version=cat_version,
        )

    def harness(self, workspace_path: str = ".") -> "AgentHarness":
        """Get or initialize the AgentHarness wrapper for this agent."""
        if not hasattr(self, "_harness") or self._harness is None:
            from nxp.orchestration.harness import AgentHarness
            self._harness = AgentHarness(self, workspace_path=workspace_path)
        return self._harness

    # ─── Server ─────────────────────────────────────────────────────────────────

    def run(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        transport: str = "http",
        reload: bool = False,
    ) -> None:
        """
        Start the agent server (blocking).

        Args:
            host: Host to bind to (default "0.0.0.0").
            port: Port to listen on (default 8000).
            transport: Transport protocol — "http" (default) or "mcp".
            reload: Enable auto-reload on file changes (HTTP only).

        Raises:
            ValueError: If an unsupported transport is specified.
        """
        import anyio

        anyio.run(self._serve, host, port, transport)

    async def _serve(self, host: str, port: int, transport: str) -> None:
        """Internal coroutine that starts the chosen transport."""
        import asyncio

        if transport == "http":
            from nxp.transport.http import HTTPTransport

            t = HTTPTransport(agent=self, host=host, port=port)

            # ── Registry: auto-register on startup ────────────────────────
            if self.registry:
                base_url = f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}"
                card = self.get_card(base_url=base_url)
                registered = await self.registry.register(card)
                if registered:
                    # Start heartbeat loop as a background task
                    asyncio.create_task(
                        self.registry.start_heartbeat_loop(card)
                    )

            await t.serve()

        elif transport == "mcp":
            from nxp.transport.mcp import MCPTransport

            t = MCPTransport(agent=self)
            await t.serve()

        elif transport == "grpc":
            from nxp.transport.grpc import GRPCTransport

            t = GRPCTransport(agent=self, host=host, port=port if port != 8000 else 50051)
            await t.serve()

        elif transport == "nxp":
            from nxp.transport.websocket import NXPTransport

            t = NXPTransport(agent=self, host=host, port=port if port != 8000 else 9000)
            await t.serve()

        else:
            raise ValueError(
                f"Unknown transport: {transport!r}. "
                "Supported: 'http', 'mcp', 'grpc', 'nxp'."
            )

    # ─── Introspection ──────────────────────────────────────────────────────────

    @property
    def skill_ids(self) -> List[str]:
        """List of all registered capability IDs."""
        return list(self._skills.keys())

    @property
    def tool_ids(self) -> List[str]:
        """List of all registered tool IDs."""
        return [k for k, s in self._skills.items() if s.type == "tool"]

    @property
    def procedure_ids(self) -> List[str]:
        """List of all registered procedure IDs."""
        return [k for k, s in self._skills.items() if s.type == "procedure"]

    def get_skill(self, skill_id: str) -> Optional[RegisteredSkill]:
        """Look up a registered skill by ID."""
        return self._skills.get(skill_id)

    def __repr__(self) -> str:
        return (
            f"Agent(name={self.name!r}, "
            f"version={self.version!r}, "
            f"skills={self.skill_ids})"
        )

    def __len__(self) -> int:
        return len(self._skills)
