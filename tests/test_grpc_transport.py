"""Unit and integration tests for the gRPC transport layer."""

from __future__ import annotations

import asyncio
import pytest

# GRPCTransport needs the optional `nxp[grpc]` extra (grpcio, protobuf).
# Skip gracefully rather than failing when it isn't installed, same as any
# other extras-gated test would in a properly packaged library.
pytest.importorskip("grpc", reason="requires the 'nxp[grpc]' extra")

from nxp import Agent, connect


@pytest.fixture
def calculator_agent() -> Agent:
    """Agent with simple arithmetic skills."""
    agent = Agent(name="calc-agent", description="A test math agent")

    @agent.skill()
    def multiply(a: float, b: float) -> float:
        """Multiply two numbers."""
        return a * b

    @agent.skill()
    async def add(a: float, b: float) -> float:
        """Add two numbers."""
        return a + b

    return agent


@pytest.mark.asyncio
async def test_grpc_transport_execution(calculator_agent: Agent):
    """
    Start the gRPC transport server in the background, connect to it
    via the grpc:// protocol scheme using AgentClient, and call skills.
    """
    # Start server in background on port 50055
    server_task = asyncio.create_task(
        calculator_agent._serve(host="127.0.0.1", port=50055, transport="grpc")
    )
    # Give the server time to start up
    await asyncio.sleep(0.3)

    try:
        # Connect to server via grpc://
        client = connect("grpc://127.0.0.1:50055")
        
        # Unary call test (sync skill)
        result_mul = await client.call("multiply", a=3.0, b=4.0)
        assert result_mul == 12.0

        # Unary call test (async skill)
        result_add = await client.call("add", a=10.0, b=5.0)
        assert result_add == 15.0

        # Test error handling (missing skill)
        with pytest.raises(RuntimeError) as exc_info:
            await client.call("nonexistent")
        assert "not found" in str(exc_info.value)

        # Clean up client
        await client.close()
    finally:
        # Cancel the server task to shutdown cleanly
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
