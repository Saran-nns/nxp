"""Unit tests for DID-based Capability Access Control (Authorization)."""

from __future__ import annotations

import asyncio
import pytest
from nxp import Agent, Identity
from nxp.transport.websocket import NXPTransport, NXPClient

@pytest.fixture
def shared_secret() -> str:
    return "symmetric-mesh-secret-key-32chars"

@pytest.fixture
def auth_server_agent(shared_secret: str) -> Agent:
    agent = Agent(
        name="tool-server",
        description="Tool server agent",
        version="0.1.0",
    )
    agent.identity = Identity(secret=shared_secret)

    @agent.skill(skill_id="a8tool")
    async def a8tool() -> str:
        return "a8_executed"

    return agent


@pytest.mark.asyncio
async def test_did_authorization_control(auth_server_agent: Agent, shared_secret: str) -> None:
    """
    Verify that ToolServer permits Agent1 to access a8tool, but rejects Agent2.
    """
    # 1. Define authorizer function
    def authorizer(client_did: str, tool_id: str) -> bool:
        # Only permit 'did:nxp:agent1' to run 'a8tool'
        if "agent1" in client_did and tool_id == "a8tool":
            return True
        return False

    # 2. Start WebSocket NXP server on port 9015
    server = NXPTransport(
        auth_server_agent,
        host="127.0.0.1",
        port=9015,
        authorizer=authorizer
    )
    server_task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.3)  # Wait for startup

    try:
        # 3. Agent 1 (Authorized Client) connects and calls a8tool
        agent1_client = NXPClient(url="ws://127.0.0.1:9015", secret=shared_secret)
        agent1_client.sender_did = "did:nxp:agent1"
        await agent1_client.connect()

        res1 = await agent1_client.call("a8tool")
        assert res1 == "a8_executed"
        await agent1_client.close()

        # 4. Agent 2 (Unauthorized Client) connects and attempts to call a8tool
        agent2_client = NXPClient(url="ws://127.0.0.1:9015", secret=shared_secret)
        agent2_client.sender_did = "did:nxp:agent2"
        await agent2_client.connect()

        with pytest.raises(RuntimeError, match="Unauthorized"):
            await agent2_client.call("a8tool")

        await agent2_client.close()

    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
