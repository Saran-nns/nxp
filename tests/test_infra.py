"""Tests for the v0.1 infrastructure layers (Identity, Budget, Observability, Runtime, Registry)."""

from __future__ import annotations

import asyncio
import os
import pytest
from httpx import AsyncClient, ASGITransport

from nxp import Agent
from nxp.security.identity import Identity
from nxp.orchestration.observe import Observability
from nxp.core.registry import Registry, create_registry_server


# ─── Identity Tests ───────────────────────────────────────────────────────────


def test_identity_did_and_signature():
    id1 = Identity(secret="super-secret-signing-key-123456", agent_name="test-agent")
    did = id1.did()
    assert did.startswith("did:nxp:test-agent:")
    assert len(id1.fingerprint()) == 8

    # Sign and verify
    payload = '{"value": 42}'
    sig = id1.sign(payload)
    assert id1.verify(payload, sig) is True
    assert id1.verify(payload + "modified", sig) is False


def test_identity_response_headers():
    id1 = Identity(secret="super-secret-signing-key-123456", agent_name="test-agent")
    body = {"result": "success"}
    headers = id1.response_headers(body)
    assert "X-Agent-DID" in headers
    assert "X-Agent-Sig" in headers
    assert "X-Agent-Ts" in headers
    assert headers["X-Agent-DID"] == id1.did()


# ─── Observability Tests ──────────────────────────────────────────────────────


def test_observability_tracing():
    obs = Observability(max_events=10)
    trace_id = obs.new_trace_id()
    assert len(trace_id) == 8

    # Record some start/end events
    obs.record(trace_id, "agent1", "skill1", "call_start", kwargs={"query": "hello"})
    obs.record(trace_id, "agent1", "skill1", "call_end", duration_ms=15.5, status="ok")

    events = obs.recent_events()
    assert len(events) == 2
    assert events[0]["event"] == "call_start"
    assert events[1]["duration_ms"] == 15.5

    trace_evts = obs.trace_events(trace_id)
    assert len(trace_evts) == 2

    # Stats
    stats = obs.skill_stats()
    assert "skill1" in stats
    assert stats["skill1"]["calls"] == 2
    assert stats["skill1"]["avg_ms"] == 7.75





# ─── Registry Server & Discovery Tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_registry_integration():
    registry_app = create_registry_server()
    
    agent_card_data = {
        "name": "registry-agent",
        "version": "1.0.0",
        "description": "Self-registering agent",
        "protocol_version": "1.0",
        "cat_version": "0.1.0",
        "url": "http://localhost:8888",
        "capabilities": {"streaming": False},
        "skills": [
            {
                "id": "do_work",
                "name": "Do Work",
                "description": "Performs tasks",
                "tags": ["work", "util"],
                "examples": [],
                "input_modes": ["application/json"],
                "output_modes": ["application/json"],
                "parameters": {"type": "object", "properties": {}},
            }
        ],
    }

    async with AsyncClient(transport=ASGITransport(app=registry_app), base_url="http://test") as client:
        # Register agent
        resp = await client.post("/register", json=agent_card_data)
        assert resp.status_code == 200
        assert resp.json()["status"] == "registered"

        # List/Search agents
        resp_list = await client.get("/agents")
        assert resp_list.status_code == 200
        assert resp_list.json()["total"] == 1
        assert resp_list.json()["agents"][0]["name"] == "registry-agent"

        # Search by tag
        resp_tag = await client.get("/agents?tags=work")
        assert resp_tag.json()["total"] == 1

        # Search by wrong tag
        resp_wrong_tag = await client.get("/agents?tags=math")
        assert resp_wrong_tag.json()["total"] == 0

        # Unregister agent
        resp_unreg = await client.delete("/agents/http://localhost:8888")
        assert resp_unreg.status_code == 200
