"""Tests for the core Agent class."""

from __future__ import annotations

import pytest

from nxp import Agent, SessionState


# ─── Agent Creation ──────────────────────────────────────────────────────────────


def test_agent_creation():
    agent = Agent(name="test-agent", description="A test agent")
    assert agent.name == "test-agent"
    assert agent.description == "A test agent"
    assert agent.version == "0.1.0"
    assert agent.skill_ids == []


def test_agent_with_all_params():
    agent = Agent(
        name="full-agent",
        description="Full config agent",
        version="2.1.0",
        provider={"name": "Acme", "url": "https://acme.com"},
        tags=["production", "math"],
    )
    assert agent.version == "2.1.0"
    assert agent.provider["name"] == "Acme"
    assert "math" in agent.tags


def test_agent_repr():
    agent = Agent(name="test", description="test")
    assert "test" in repr(agent)


# ─── Skill Registration ──────────────────────────────────────────────────────────


def test_skill_decorator_basic():
    agent = Agent(name="test", description="test")

    @agent.skill()
    def my_skill(x: int) -> int:
        """Double the input."""
        return x * 2

    assert "my_skill" in agent._skills
    skill = agent._skills["my_skill"]
    assert skill.description == "Double the input."
    assert skill.name == "My Skill"


def test_skill_decorator_with_metadata():
    agent = Agent(name="test", description="test")

    @agent.skill(
        skill_id="web_search",
        name="Web Search",
        tags=["search", "web"],
        examples=["Search for AI news"],
    )
    def search_web(query: str) -> str:
        """Search the web."""
        return f"Results for {query}"

    skill = agent._skills["web_search"]
    assert skill.skill_id == "web_search"
    assert skill.name == "Web Search"
    assert "search" in skill.tags
    assert "Search for AI news" in skill.examples


def test_tool_alias():
    """@agent.tool() should work identically to @agent.skill()"""
    agent = Agent(name="test", description="test")

    @agent.tool()
    def my_tool(x: str) -> str:
        """A tool."""
        return x

    assert "my_tool" in agent._skills


def test_skill_function_returned_unmodified():
    """The original function should be returned unchanged by the decorator."""
    agent = Agent(name="test", description="test")

    @agent.skill()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    assert add(3, 4) == 7  # Original function still works


def test_agent_len():
    agent = Agent(name="test", description="test")

    @agent.skill()
    def s1() -> str:
        """Skill 1."""
        return "s1"

    @agent.skill()
    def s2() -> str:
        """Skill 2."""
        return "s2"

    assert len(agent) == 2


# ─── Skill Execution ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_skill_execution():
    agent = Agent(name="test", description="test")

    @agent.skill()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    result = await agent._skills["add"].execute(a=3, b=4)
    assert result == 7


@pytest.mark.asyncio
async def test_async_skill_execution():
    agent = Agent(name="test", description="test")

    @agent.skill()
    async def fetch(url: str) -> str:
        """Fetch a URL."""
        return f"Content of {url}"

    result = await agent._skills["fetch"].execute(url="http://example.com")
    assert result == "Content of http://example.com"


# ─── Agent Card ──────────────────────────────────────────────────────────────────


def test_get_card_basic():
    agent = Agent(name="MyAgent", description="Does things", version="2.0.0")
    card = agent.get_card(base_url="http://localhost:8000")

    assert card.name == "MyAgent"
    assert card.description == "Does things"
    assert card.version == "2.0.0"
    assert card.url == "http://localhost:8000"
    assert card.protocol_version == "1.0"


def test_get_card_with_skills():
    agent = Agent(name="test", description="test")

    @agent.skill(tags=["math"])
    def calculate(x: float) -> float:
        """Do math."""
        return x * 2

    card = agent.get_card(base_url="http://localhost:8000")
    assert len(card.skills) == 1
    assert card.skills[0].id == "calculate"
    assert "math" in card.skills[0].tags


def test_get_card_with_provider():
    agent = Agent(
        name="test",
        description="test",
        provider={"name": "Acme Corp", "url": "https://acme.com"},
    )
    card = agent.get_card(base_url="http://localhost:8000")
    assert card.provider is not None
    assert card.provider.name == "Acme Corp"
    assert card.provider.url == "https://acme.com"


def test_get_skill():
    agent = Agent(name="test", description="test")

    @agent.skill()
    def my_skill() -> str:
        """A skill."""
        return "hello"

    assert agent.get_skill("my_skill") is not None
    assert agent.get_skill("nonexistent") is None


# ─── Working Memory ──────────────────────────────────────────────────────────────


def test_session_state_basic():
    mem = SessionState()
    mem.set("key", "value")
    assert mem.get("key") == "value"
    assert mem.get("missing") is None
    assert mem.get("missing", "default") == "default"


def test_session_state_delete():
    mem = SessionState()
    mem.set("k", "v")
    mem.delete("k")
    assert "k" not in mem


def test_session_state_clear():
    mem = SessionState()
    mem.set("a", 1)
    mem.set("b", 2)
    mem.clear()
    assert len(mem) == 0


def test_session_state_initial():
    mem = SessionState(initial={"x": 10, "y": 20})
    assert mem.get("x") == 10
    assert len(mem) == 2


def test_session_state_repr():
    mem = SessionState(initial={"key": "val"})
    assert "key" in repr(mem)
