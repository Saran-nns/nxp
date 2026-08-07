"""Unit tests for declarative class decorators and harness shortcut."""

from __future__ import annotations

import pytest
import nxp

@nxp.agent(name="dec-agent", description="Declarative test agent", harness=True)
class DeclarativeAgent:
    def __init__(self, prefix: str = "audit_") -> None:
        self.prefix = prefix

    @nxp.tool()
    def get_version(self) -> str:
        """Get software version."""
        return "1.0.0"

    @nxp.skill()
    def run_check(self, value: int = 10) -> str:
        """Evaluate status checks."""
        return f"{self.prefix}check_ok_{value}"


def test_declarative_agent_class():
    """
    Verify class-based decorator returns subclass of Agent and holds methods.
    """
    # Instantiate declarative agent class
    instance = DeclarativeAgent(prefix="sys_")

    # Verify inheritance and core fields
    assert isinstance(instance, nxp.Agent)
    assert isinstance(instance, DeclarativeAgent)
    assert instance.name == "dec-agent"
    assert instance.description == "Declarative test agent"
    assert instance.prefix == "sys_"

    # Verify registered capabilities
    assert "get_version" in instance._skills
    assert "run_check" in instance._skills

    # Assert capability type metadata
    assert instance._skills["get_version"].type == "tool"
    assert instance._skills["run_check"].type == "skill"

    # Assert the harness is automatically loaded
    assert hasattr(instance, "_harness")
    assert instance._harness is not None
    assert "get_version" in instance.harness().tools
    assert "run_check" in instance.harness().skills


def test_agent_harness_method():
    """
    Verify agent.harness() method creates, caches, and returns the harness.
    """
    # Create simple agent
    simple = nxp.Agent(name="simple", description="Simple test agent")

    @simple.tool()
    def query() -> str:
        return "yes"

    # Assert no harness initially
    assert not hasattr(simple, "_harness")

    # Get harness via method
    h = simple.harness()
    assert isinstance(h, nxp.AgentHarness)
    assert "query" in h.tools

    # Verify caching (repeated call returns exact same instance)
    assert simple.harness() is h


@nxp.agent(name="custom-dec", description="Agent with custom harness runner")
class CustomOrchestratorAgent:
    @nxp.tool()
    def get_time(self) -> str:
        return "now"

    @nxp.harness()
    def custom_run(self, task: str) -> str:
        return f"custom_run_completed_for_{task}"


@pytest.mark.asyncio
async def test_custom_harness_decorators():
    """
    Verify both instance-level and class-level custom harness loop decorators.
    """
    # 1. Instance decorator test
    agent = nxp.Agent(name="instance-custom", description="...")
    h = agent.harness()

    @h
    def my_runner(task: str) -> str:
        return f"my_runner_ran_{task}"

    res = await agent.harness().run("do-something")
    assert res["status"] == "success"
    assert res["result"] == "my_runner_ran_do-something"

    # 2. Class decorator test
    dec_agent = CustomOrchestratorAgent()
    assert dec_agent.harness().custom_runner is not None

    res_dec = await dec_agent.harness().run("check-time")
    assert res_dec["status"] == "success"
    assert res_dec["result"] == "custom_run_completed_for_check-time"
