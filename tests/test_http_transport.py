"""
Integration tests for the HTTP transport.

These tests start a real FastAPI server in-process using
httpx.AsyncClient(app=...) for fast, no-network testing.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from nxp import Agent
from nxp.transport.http import HTTPTransport


@pytest.fixture
def calculator_agent() -> Agent:
    """A simple agent with math skills."""
    agent = Agent(name="calculator", description="Does math", version="1.0.0")

    @agent.skill(tags=["math"], examples=["Add 1 and 2"])
    def add(a: float, b: float) -> float:
        """Add two numbers."""
        return a + b

    @agent.skill(tags=["math"])
    def multiply(a: float, b: float) -> float:
        """Multiply two numbers."""
        return a * b

    @agent.skill()
    async def echo(message: str) -> str:
        """Echo a message back."""
        return message

    return agent


@pytest.fixture
def transport(calculator_agent: Agent) -> HTTPTransport:
    return HTTPTransport(agent=calculator_agent, host="localhost", port=8000)


@pytest.fixture
def app(transport: HTTPTransport):
    return transport.app


# ─── Agent Card ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_card_endpoint(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "calculator"
    assert card["version"] == "1.0.0"
    assert len(card["skills"]) == 3
    skill_ids = [s["id"] for s in card["skills"]]
    assert "add" in skill_ids
    assert "multiply" in skill_ids


@pytest.mark.asyncio
async def test_agent_card_has_cat_version(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/.well-known/agent-card.json")
    assert "cat_version" in resp.json()


# ─── Health ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["agent"] == "calculator"
    assert data["skills"] == 3


# ─── Skills ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_skills(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/skills")
    assert resp.status_code == 200
    skills = resp.json()["skills"]
    assert len(skills) == 3


@pytest.mark.asyncio
async def test_get_skill(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/skills/add")
    assert resp.status_code == 200
    skill = resp.json()
    assert skill["id"] == "add"
    assert "math" in skill["tags"]


@pytest.mark.asyncio
async def test_get_skill_not_found(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/skills/nonexistent")
    assert resp.status_code == 404


# ─── Call Skills ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_skill_sync(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/skills/add", json={"kwargs": {"a": 3.0, "b": 4.0}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == 7.0
    assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_call_skill_async(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/skills/echo", json={"kwargs": {"message": "hello nxp"}})
    assert resp.status_code == 200
    assert resp.json()["result"] == "hello nxp"


@pytest.mark.asyncio
async def test_call_skill_not_found(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/skills/nonexistent", json={"kwargs": {}})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_call_skill_bad_args(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/skills/add", json={"kwargs": {"a": "not_a_number"}})
    # Should still call but may error at runtime
    assert resp.status_code in (200, 422, 500)


# ─── Tasks ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_task(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/tasks", json={"skill_id": "multiply", "kwargs": {"a": 6.0, "b": 7.0}}
        )
    assert resp.status_code == 202
    task = resp.json()
    assert "task_id" in task
    assert task["status"] in ("submitted", "working", "completed")


@pytest.mark.asyncio
async def test_submit_task_invalid_skill(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/tasks", json={"skill_id": "nonexistent", "kwargs": {}})
    assert resp.status_code == 202
    task = resp.json()
    assert task["status"] == "failed"


@pytest.mark.asyncio
async def test_get_task(app, transport):
    """Submit and poll a task to completion."""
    import asyncio

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Submit
        resp = await client.post(
            "/tasks", json={"skill_id": "add", "kwargs": {"a": 10.0, "b": 5.0}}
        )
        task_id = resp.json()["task_id"]

        # Allow background task to complete
        await asyncio.sleep(0.2)

        # Poll
        poll_resp = await client.get(f"/tasks/{task_id}")

    assert poll_resp.status_code == 200
    result = poll_resp.json()
    assert result["status"] == "completed"
    assert result["result"] == 15.0


@pytest.mark.asyncio
async def test_get_task_not_found(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/tasks/nonexistent-id")
    assert resp.status_code == 404
