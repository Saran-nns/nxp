"""
AgentClient — Connect to and call remote agents.

Usage
-----
    from nxp import connect

    # Shorthand factory
    client = connect("http://localhost:8000")

    # Call a skill (direct, synchronous result)
    result = await client.call("add", a=10, b=20)

    # Delegate a task (async, background execution)
    result = await client.task("summarize", text="...")

    # Inspect the remote agent
    card = await client.get_card()
    print(card.name, card.skills)
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
import httpx
from nxp.core.card import AgentCard, SkillDefinition


class AgentClient:
    """
    Client for connecting to and calling a remote nxp agent.

    Supports both HTTP (A2A) and gRPC protocols transparently.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        """
        Create an AgentClient.

        Args:
            base_url: Base URL of the remote agent, e.g. "http://localhost:8000" or "grpc://localhost:50051".
            api_key:  Optional Bearer token for authenticated HTTP agents.
            timeout:  HTTP request timeout in seconds (default 60).
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._card_cache: Optional[AgentCard] = None

        # Detect gRPC vs HTTP
        self.is_grpc = self.base_url.startswith("grpc://")
        self.grpc_channel: Optional[Any] = None
        self.grpc_stub: Optional[Any] = None

        if self.is_grpc:
            import grpc
            from nxp.transport import agent_pb2_grpc
            # Remove protocol scheme for grpc target
            target = self.base_url.replace("grpc://", "")
            self.grpc_channel = grpc.aio.insecure_channel(target)
            self.grpc_stub = agent_pb2_grpc.AgentServiceStub(self.grpc_channel)

    # ─── Auth Headers ────────────────────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    # ─── Agent Card ─────────────────────────────────────────────────────────────

    async def get_card(self, *, use_cache: bool = True) -> AgentCard:
        """
        Fetch the remote agent's Agent Card.

        Returns:
            AgentCard with name, description, skills, capabilities, etc.
        """
        if self.is_grpc:
            return AgentCard(
                name="grpc-agent",
                description="Agent exposed via gRPC high-speed transport",
                version="0.1.0",
                url=self.base_url,
                skills=[],
            )

        if use_cache and self._card_cache is not None:
            return self._card_cache

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/.well-known/agent-card.json",
                headers=self._headers(),
            )
            resp.raise_for_status()
            self._card_cache = AgentCard(**resp.json())
            return self._card_cache

    # ─── Skill Calls ────────────────────────────────────────────────────────────

    async def call(self, skill_id: str, **kwargs: Any) -> Any:
        """
        Directly call a skill on the remote agent and wait for its result.

        Supports both HTTP (A2A POST /skills/...) and gRPC Execute RPC calls.
        """
        if self.is_grpc:
            from nxp.transport import agent_pb2
            import json
            import grpc
            
            req = agent_pb2.ExecuteRequest(
                skill_id=skill_id,
                kwargs_json=json.dumps(kwargs),
            )
            try:
                resp = await self.grpc_stub.Execute(req)
                if resp.error:
                    raise RuntimeError(f"gRPC Skill call error: {resp.error}")
                return json.loads(resp.result_json) if resp.result_json else None
            except grpc.RpcError as exc:
                raise RuntimeError(f"gRPC Skill call failed: {exc.details()}")

        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.post(
                f"{self.base_url}/skills/{skill_id}",
                json={"kwargs": kwargs},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("result")

    async def task(
        self,
        skill_id: str,
        *,
        poll_interval: float = 0.5,
        max_wait: float = 300.0,
        **kwargs: Any,
    ) -> Any:
        """
        Delegate a long-running task to the remote agent and wait for completion.

        Unlike ``call()``, this submits the task and polls until it is done.
        Use this for skills that take a long time to complete.

        Args:
            skill_id: The ID of the skill to call as a task.
            poll_interval: Seconds between status polls (default 0.5).
            max_wait: Maximum seconds to wait before raising TimeoutError (default 300).
            **kwargs: Keyword arguments passed to the skill.

        Returns:
            The completed task's result value.

        Raises:
            RuntimeError: If the task fails.
            TimeoutError: If the task doesn't complete within max_wait seconds.

        Example:
            result = await client.task("summarize", text="...")
        """
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            # Submit the task
            resp = await http.post(
                f"{self.base_url}/tasks",
                json={"skill_id": skill_id, "kwargs": kwargs},
                headers=self._headers(),
            )
            resp.raise_for_status()
            task_data = resp.json()
            task_id: str = task_data["task_id"]

            # Poll until terminal state
            elapsed = 0.0
            while elapsed < max_wait:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                status_resp = await http.get(
                    f"{self.base_url}/tasks/{task_id}",
                    headers=self._headers(),
                )
                status_resp.raise_for_status()
                status = status_resp.json()

                state = status.get("status", "")
                if state == "completed":
                    return status.get("result")
                elif state == "failed":
                    raise RuntimeError(
                        f"Task '{task_id}' failed: {status.get('error', 'unknown error')}"
                    )
                elif state == "canceled":
                    raise RuntimeError(f"Task '{task_id}' was canceled.")

            raise TimeoutError(
                f"Task '{task_id}' did not complete within {max_wait}s."
            )

    # ─── Helpers ─────────────────────────────────────────────────────────────────

    async def list_skills(self) -> List[SkillDefinition]:
        """
        List all skills available on the remote agent.

        Returns:
            List of SkillDefinition objects.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.get(
                f"{self.base_url}/skills",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return [SkillDefinition(**s) for s in data.get("skills", [])]

    async def health(self) -> Dict[str, Any]:
        """Check the remote agent's health status."""
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.get(f"{self.base_url}/health")
            resp.raise_for_status()
            return resp.json()

    async def close(self) -> None:
        """Close any open connections (including gRPC channels)."""
        if self.grpc_channel is not None:
            await self.grpc_channel.close()

    async def __aenter__(self) -> AgentClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    def __getattr__(self, name: str) -> Any:
        """Dynamically route skill calls to self.call(name, **kwargs)."""
        if name.startswith("_") or name in ("close", "health", "get_card", "list_skills", "call", "task", "base_url", "api_key", "timeout", "is_grpc", "grpc_stub", "grpc_channel"):
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

        async def _dynamic_call(**kwargs: Any) -> Any:
            return await self.call(name, **kwargs)

        return _dynamic_call

    def __repr__(self) -> str:
        return f"AgentClient(url={self.base_url!r})"


# ─── Factory Function ───────────────────────────────────────────────────────────


def connect(url: str, api_key: Optional[str] = None, timeout: float = 60.0) -> Any:
    """
    Create an AgentClient or NXPClient connected to the given URL.

    This is the primary way to connect to a remote agent.
    """
    if url.startswith("ws://"):
        from nxp.transport.websocket import NXPClient
        return NXPClient(url)
    return AgentClient(base_url=url, api_key=api_key, timeout=timeout)
