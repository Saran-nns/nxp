"""
Registry — Agent Marketplace and Discovery for the Internet of Agents.

Problem Solved
--------------
"Agent marketplaces — Currently: Nascent | Future: Verified agent registries"

Without this: agents are siloed — you must hardcode URLs to connect agents.
With this:    agents register themselves, clients discover by name/tag,
              dead agents are auto-pruned via heartbeats.

Usage
-----
    # 1. Start the registry server (once, shared across all agents):
    #    nxp registry start --port 9999

    # 2. Agents auto-register on startup:
    from nxp import Agent
    from nxp.registry import Registry

    agent = Agent(
        name="research-agent",
        description="...",
        registry=Registry(url="http://localhost:9999"),
    )
    agent.run(port=8000)
    # → Agent registers at http://localhost:9999 and sends heartbeats every 30s

    # 3. Clients discover agents dynamically:
    from nxp.registry import Registry

    reg = Registry(url="http://localhost:9999")
    agents = await reg.find(tags=["research"])   # → [AgentCard(...)]
    agent_url = agents[0].url                    # → "http://localhost:8000"

    # Or via CLI:
    #   nxp registry list http://localhost:9999
    #   nxp registry find http://localhost:9999 --tag math
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
except ImportError:
    httpx = None
    FastAPI = Any  # type: ignore
    JSONResponse = Any  # type: ignore


from nxp.card import AgentCard


# ─── Registry Client ─────────────────────────────────────────────────────────


@dataclass
class Registry:
    """
    Client for registering with and discovering from a nxp registry server.

    Args:
        url:                  URL of the registry server, e.g. "http://localhost:9999".
        heartbeat_interval:   Seconds between heartbeat pings (default 30).
                              The server prunes agents that miss 3 heartbeats (90s).
    """

    url: str
    heartbeat_interval: int = 30

    def __post_init__(self) -> None:
        self.url = self.url.rstrip("/")

    # ─── Registration ─────────────────────────────────────────────────────────

    async def register(self, card: AgentCard) -> bool:
        """
        Register an agent with the registry.

        Called automatically by Agent.run() on startup.

        Args:
            card: The agent's AgentCard.

        Returns:
            True if registration succeeded, False otherwise.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self.url}/register",
                    json=card.model_dump(by_alias=False),
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def unregister(self, agent_url: str) -> bool:
        """Remove an agent from the registry."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.delete(f"{self.url}/agents/{agent_url}")
                return resp.status_code == 200
        except Exception:
            return False

    async def heartbeat(self, card: AgentCard) -> bool:
        """Send a heartbeat to keep registration alive."""
        return await self.register(card)

    async def start_heartbeat_loop(self, card: AgentCard) -> None:
        """
        Start a background loop that sends heartbeats to the registry.

        This runs forever (until cancelled) and keeps the agent's
        registration alive. Called automatically by Agent.run().
        """
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self.heartbeat(card)
            except Exception:
                pass  # Non-fatal — agent keeps running

    # ─── Discovery ────────────────────────────────────────────────────────────

    async def find(
        self,
        *,
        tags: Optional[List[str]] = None,
        name: Optional[str] = None,
    ) -> List[AgentCard]:
        """
        Discover agents in the registry.

        Args:
            tags: Filter by skill tags (e.g. ["math", "research"]).
            name: Filter by agent name (partial match).

        Returns:
            List of AgentCard objects for matching, live agents.

        Example:
            agents = await reg.find(tags=["research"])
            researcher = connect(agents[0].url)
        """
        params: Dict[str, str] = {}
        if tags:
            params["tags"] = ",".join(tags)
        if name:
            params["name"] = name

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.url}/agents", params=params)
            resp.raise_for_status()
            return [AgentCard(**a) for a in resp.json().get("agents", [])]

    async def list_all(self) -> List[AgentCard]:
        """Return all registered live agents."""
        return await self.find()

    async def health(self) -> Dict[str, Any]:
        """Check the registry server health."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{self.url}/health")
            resp.raise_for_status()
            return resp.json()

    def __repr__(self) -> str:
        return f"Registry(url={self.url!r}, heartbeat={self.heartbeat_interval}s)"


# ─── Registry Server ─────────────────────────────────────────────────────────


def create_registry_server() -> FastAPI:
    """
    Create a standalone nxp Registry server.

    This FastAPI app can be started with uvicorn and shared across
    all agents in your deployment.

    Start via CLI:
        nxp registry start --port 9999

    Or programmatically:
        import uvicorn
        from nxp.registry import create_registry_server
        uvicorn.run(create_registry_server(), port=9999)

    Endpoints:
        POST   /register          — Register an agent
        GET    /agents            — List/search agents
        DELETE /agents/{url}      — Unregister an agent
        GET    /health            — Registry health
    """
    app = FastAPI(
        title="nxp Registry",
        description="Agent discovery and marketplace for the Internet of Agents",
        version="0.1.0",
    )

    # Internal store: agent_url → {card: dict, last_seen: float}
    _store: Dict[str, Dict[str, Any]] = {}

    # Heartbeat timeout: agents not seen in 90s are considered dead
    _HEARTBEAT_TIMEOUT = 90.0

    def _prune() -> None:
        """Remove agents that haven't sent a heartbeat recently."""
        cutoff = time.time() - _HEARTBEAT_TIMEOUT
        dead = [url for url, entry in _store.items() if entry["last_seen"] < cutoff]
        for url in dead:
            del _store[url]

    @app.post("/register", tags=["registry"])
    async def register(card: Dict[str, Any]) -> Dict[str, Any]:
        """Register or refresh an agent's entry in the registry."""
        url = card.get("url", "")
        if not url:
            return JSONResponse({"error": "Agent card must include a 'url' field."}, status_code=400)
        _store[url] = {"card": card, "last_seen": time.time()}
        return {"status": "registered", "url": url, "total_agents": len(_store)}

    @app.get("/agents", tags=["registry"])
    async def list_agents(
        tags: str = "",
        name: str = "",
    ) -> Dict[str, Any]:
        """
        List all live agents, optionally filtered by tags or name.

        Automatically prunes agents that have missed heartbeats.
        """
        _prune()
        entries = list(_store.values())

        # Filter by name (partial, case-insensitive)
        if name:
            entries = [
                e for e in entries
                if name.lower() in e["card"].get("name", "").lower()
            ]

        # Filter by tags (any skill must have all requested tags)
        if tags:
            filter_tags = {t.strip().lower() for t in tags.split(",") if t.strip()}
            entries = [
                e for e in entries
                if _card_has_tags(e["card"], filter_tags)
            ]

        return {
            "agents": [e["card"] for e in entries],
            "total": len(entries),
        }

    @app.delete("/agents/{agent_url:path}", tags=["registry"])
    async def unregister(agent_url: str) -> Dict[str, Any]:
        """Explicitly unregister an agent."""
        removed = _store.pop(agent_url, None)
        if removed:
            return {"status": "unregistered", "url": agent_url}
        return JSONResponse({"error": f"Agent '{agent_url}' not found."}, status_code=404)

    @app.get("/health", tags=["meta"])
    async def health() -> Dict[str, Any]:
        """Registry health and statistics."""
        _prune()
        return {
            "status": "ok",
            "live_agents": len(_store),
            "heartbeat_timeout_s": _HEARTBEAT_TIMEOUT,
        }

    @app.get("/", tags=["meta"])
    async def root() -> Dict[str, Any]:
        """Registry info."""
        _prune()
        return {
            "service": "nxp Registry",
            "version": "0.1.0",
            "live_agents": len(_store),
            "endpoints": {
                "register": "POST /register",
                "list_agents": "GET /agents",
                "filter_by_tag": "GET /agents?tags=math,research",
                "filter_by_name": "GET /agents?name=calculator",
                "unregister": "DELETE /agents/{url}",
                "health": "GET /health",
                "docs": "GET /docs",
            },
        }

    return app


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _card_has_tags(card: Dict[str, Any], filter_tags: set) -> bool:
    """Check if any skill in the agent card has all the requested tags."""
    all_tags = set()
    for skill in card.get("skills", []):
        for tag in skill.get("tags", []):
            all_tags.add(tag.lower())
    return bool(filter_tags & all_tags)
