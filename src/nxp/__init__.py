"""
Nexus Exchange Protocol (NXP) Python SDK
==========================================
Production-grade Agent-to-Agent (A2A) Zero-Trust Protocol & Framework.

Quick Start
-----------
    import nxp

    agent = nxp.NXPAgent(name="my-agent", description="Does useful things")

    @agent.skill(tags=["demo"])
    def greet(name: str) -> str:
        \"\"\"Greet someone warmly.\"\"\"
        return f"Hello, {name}!"

    # Start the agent server
    agent.run(port=8000)

    # In another process, connect and call
    client = nxp.connect("http://localhost:8000")
    result = await client.call("greet", name="World")
"""

__version__ = "1.0.0"
__author__ = "Nexus Exchange Protocol Contributors"
__license__ = "MIT"

from nxp.agent import Agent, Agent as NXPAgent
from nxp.client import AgentClient, AgentClient as NXPClient, connect
from nxp.card import AgentCard, AgentCapabilities, Provider, SkillDefinition
from nxp.memory.session import SessionState
from nxp.identity import Identity
from nxp.observe import Observability
from nxp.registry import Registry
from nxp.graph import StateGraph, START, END
from nxp.loop import FeedbackLoop, ReflexiveAgent
from nxp.harness import AgentHarness, ContextManager, ExecutionLayer, EnvironmentHarness
from nxp.decorators import agent, tool, skill, procedure, harness
from nxp.transport.base import BaseTransport
from nxp.transport.http import HTTPTransport
from nxp.transport.websocket import NXPTransport as WebSocketTransport, NXPTransport
from nxp.security.crypto import ZeroTrustSecurity
from nxp.security.sandbox import ToolSandbox

__all__ = [
    # Core Agents
    "Agent",
    "NXPAgent",
    "AgentHarness",
    "ContextManager",
    "ExecutionLayer",
    "EnvironmentHarness",
    # Workflows & Loops
    "StateGraph",
    "START",
    "END",
    "FeedbackLoop",
    "ReflexiveAgent",
    # Decorators
    "agent",
    "tool",
    "skill",
    "procedure",
    "harness",
    # Transports & Clients
    "NXPTransport",
    "BaseTransport",
    "HTTPTransport",
    "WebSocketTransport",
    "NXPClient",
    "AgentClient",
    "connect",
    # Security & Sandboxing
    "ZeroTrustSecurity",
    "ToolSandbox",
    # Data models
    "AgentCard",
    "AgentCapabilities",
    "Provider",
    "SkillDefinition",
    # Memory & Identity
    "SessionState",
    "Identity",
    "Observability",
    "Registry",
    # Metadata
    "__version__",
    "__author__",
    "__license__",
]
