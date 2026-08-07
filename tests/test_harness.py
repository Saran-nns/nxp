"""Unit tests for NXP Agent Harness and Capability Types."""

from __future__ import annotations

import asyncio
import pytest
from nxp import Agent, AgentHarness, ContextManager

@pytest.fixture
def complex_agent() -> Agent:
    agent = Agent(name="test-harness-agent", description="Agent for testing capability types")

    @agent.tool()
    def read_config(path: str) -> str:
        """Read configuration file from active workspace."""
        return f"config_at_{path}"

    @agent.skill()
    def assess_risk(amount: float = 0.0) -> str:
        """Assess transaction risk."""
        return "HIGH" if amount > 1000 else "LOW"

    @agent.procedure()
    async def run_audit() -> str:
        """Run multi-step system audit."""
        return "audit_completed"

    return agent


def test_capability_registration(complex_agent: Agent):
    """
    Verify distinct decorators set appropriate type fields on RegisteredSkill objects.
    """
    assert "read_config" in complex_agent._skills
    assert "assess_risk" in complex_agent._skills
    assert "run_audit" in complex_agent._skills

    # Assert correct type tagging
    assert complex_agent._skills["read_config"].type == "tool"
    assert complex_agent._skills["assess_risk"].type == "skill"
    assert complex_agent._skills["run_audit"].type == "procedure"


def test_card_capability_types(complex_agent: Agent):
    """
    Verify AgentCard compiles distinct capability types correctly.
    """
    card = complex_agent.get_card()
    skill_defs = {s.id: s for s in card.skills}

    assert "read_config" in skill_defs
    assert skill_defs["read_config"].type == "tool"

    assert "assess_risk" in skill_defs
    assert skill_defs["assess_risk"].type == "skill"

    assert "run_audit" in skill_defs
    assert skill_defs["run_audit"].type == "procedure"


@pytest.mark.asyncio
async def test_harness_execution_and_routing(complex_agent: Agent):
    """
    Verify AgentHarness execution flow, type routing, and planning context.
    """
    harness = AgentHarness(complex_agent)

    # Check categorizations on the harness
    assert "read_config" in harness.tools
    assert "assess_risk" in harness.skills
    assert "run_audit" in harness.procedures

    # Run loop fallback (should execute first skill 'assess_risk' because no procedure matched)
    res = await harness.run("Find transaction hazard rating")
    assert res["status"] == "success"
    # assess_risk requires principal amount, defaults parameter
    assert res["result"] == "LOW"  # assess_risk defaults amount=0.0 implicitly

    # Run loop matched procedure
    res_proc = await harness.run("Execute run-audit procedure")
    assert res_proc["status"] == "success"
    assert res_proc["result"] == "audit_completed"

    # Verify context history contains traces of planning and execution
    history = res_proc["history"]
    assert any(h["role"] == "orchestrator" and h["action"] == "plan" for h in history)
    assert any(h["action"] == "run_audit" and h["result"] == "audit_completed" for h in history)


@pytest.mark.asyncio
async def test_harness_permissions(complex_agent: Agent):
    """
    Verify ContextManager permission gates block unauthorized execution.
    """
    harness = AgentHarness(complex_agent)

    # Register custom restriction
    harness.context.permissions["execute:read_config"] = False

    with pytest.raises(PermissionError) as exc_info:
        await harness.executor.execute("read_config", harness.context, path="config.json")
    
    assert "Permission denied" in str(exc_info.value)
