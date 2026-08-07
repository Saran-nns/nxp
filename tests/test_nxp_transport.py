"""Unit and integration tests for the NXP (WebSocket) transport layer."""

from __future__ import annotations

import asyncio
import pytest

from nxp import Agent, connect


@pytest.fixture
def calc_nxp_agent() -> Agent:
    """Agent with simple skills for NXP testing."""
    agent = Agent(name="calc-nxp-agent", description="A test NXP agent")

    @agent.skill()
    def multiply(a: float, b: float) -> float:
        """Multiply two numbers."""
        return a * b

    from nxp.memory.session import SessionState

    @agent.skill()
    def store_item(key: str, val: str, memory: SessionState) -> str:
        """Store item in session memory."""
        memory.set(key, val)
        return "stored"

    @agent.skill()
    def retrieve_item(key: str, memory: SessionState) -> str:
        """Retrieve item from session memory."""
        return str(memory.get(key, "missing"))

    return agent


@pytest.mark.asyncio
async def test_nxp_transport_execution(calc_nxp_agent: Agent):
    """
    Start the NXP WebSocket transport server, connect to it,
    handshake and retrieve the Agent Card, and execute skills.
    """
    # Start NXP server on port 9005
    server_task = asyncio.create_task(
        calc_nxp_agent._serve(host="127.0.0.1", port=9005, transport="nxp")
    )
    # Give server time to start up
    await asyncio.sleep(0.3)

    try:
        # Connect to NXP server via ws://
        client = connect("ws://127.0.0.1:9005")
        
        # Connect & Handshake
        await client.connect()
        
        # Assert Agent Card metadata is correct
        assert client.card.name == "calc-nxp-agent"
        assert len(client.card.skills) == 3

        # RPC Call test
        result = await client.call("multiply", a=3.0, b=5.0)
        assert result == 15.0

        # Stateful memory session test
        store_res = await client.call("store_item", key="user", val="Bob")
        assert store_res == "stored"

        retrieve_res = await client.call("retrieve_item", key="user")
        assert retrieve_res == "Bob"

        # RPC Call error test
        with pytest.raises(RuntimeError) as exc_info:
            await client.call("nonexistent")
        assert "not found" in str(exc_info.value)

        # Clean up
        await client.close()
    finally:
        # Cancel server task
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_nxp_client_ergonomics(calc_nxp_agent: Agent):
    """
    Test context manager and dynamic attribute routing for skills.
    """
    # Start NXP server on port 9006
    server_task = asyncio.create_task(
        calc_nxp_agent._serve(host="127.0.0.1", port=9006, transport="nxp")
    )
    await asyncio.sleep(0.3)

    try:
        from nxp.transport.websocket import NXPClient

        # Test context manager and dynamic method calling
        async with NXPClient("ws://127.0.0.1:9006") as client:
            assert client.card.name == "calc-nxp-agent"
            
            # Call remote skill dynamically as if it were a local method!
            res = await client.multiply(a=4.0, b=5.0)
            assert res == 20.0
            
            # Stateful memory call
            store_res = await client.store_item(key="role", val="Admin")
            assert store_res == "stored"
            
            retrieve_res = await client.retrieve_item(key="role")
            assert retrieve_res == "Admin"
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
