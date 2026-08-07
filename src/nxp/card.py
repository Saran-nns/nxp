"""
Agent Card — A2A-compatible Pydantic models for agent discovery.

The Agent Card is automatically served at /.well-known/agent-card.json
and describes the agent's identity, capabilities, and available skills.

Reference: Google A2A Protocol Specification v1.0
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SkillParameter(BaseModel):
    """JSON Schema for a single skill parameter."""

    type: str = "string"
    description: Optional[str] = None
    default: Optional[Any] = None
    nullable: Optional[bool] = None
    items: Optional[Dict[str, Any]] = None  # for array types
    enum: Optional[List[Any]] = None


class SkillDefinition(BaseModel):
    """
    Definition of a single skill exposed by an agent.

    Skills are the A2A equivalent of MCP tools — they are callable
    capabilities that an agent advertises and other agents can invoke.
    """

    id: str = Field(..., description="Unique skill identifier (used in API calls)")
    name: str = Field(..., description="Human-readable skill name")
    description: str = Field(..., description="LLM-facing description of what this skill does")
    tags: List[str] = Field(default_factory=list, description="Categorization tags")
    examples: List[str] = Field(
        default_factory=list, description="Example queries that trigger this skill"
    )
    input_modes: List[str] = Field(
        default=["text/plain", "application/json"],
        description="MIME types this skill accepts",
    )
    output_modes: List[str] = Field(
        default=["text/plain", "application/json"],
        description="MIME types this skill returns",
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for skill parameters",
    )
    type: str = Field(
        default="skill",
        description="Capability type: 'tool', 'skill', or 'procedure'",
    )


class AgentCapabilities(BaseModel):
    """Capabilities advertised by the agent."""

    streaming: bool = Field(default=False, description="Supports SSE streaming responses")
    push_notifications: bool = Field(
        default=False, description="Supports webhook-style push notifications"
    )
    extended_agent_card: bool = Field(
        default=False, description="Exposes a full extended agent card"
    )


class Provider(BaseModel):
    """Organization or individual that created this agent."""

    name: str = Field(..., description="Provider name")
    url: Optional[str] = Field(default=None, description="Provider homepage URL")
    support_contact: Optional[str] = Field(
        default=None, description="Support email or URL"
    )


class AgentCard(BaseModel):
    """
    A2A-compatible Agent Card describing this agent.

    Automatically served at /.well-known/agent-card.json when the
    agent is running with HTTP transport.

    Based on: Google A2A Protocol Specification v1.0
    Extended with: cat_version for CAT-specific metadata
    """

    name: str = Field(..., description="Agent name")
    description: str = Field(..., description="What this agent does")
    version: str = Field(default="0.1.0", description="Agent version (semver)")
    protocol_version: str = Field(
        default="1.0", description="A2A protocol version"
    )
    url: str = Field(..., description="Base URL of the agent's A2A endpoint")
    capabilities: AgentCapabilities = Field(
        default_factory=AgentCapabilities,
        description="Agent capabilities",
    )
    default_input_modes: List[str] = Field(
        default=["text/plain", "application/json"],
        description="Default MIME types the agent accepts",
    )
    default_output_modes: List[str] = Field(
        default=["text/plain", "application/json"],
        description="Default MIME types the agent returns",
    )
    skills: List[SkillDefinition] = Field(
        default_factory=list,
        description="Skills (callable capabilities) this agent exposes",
    )
    provider: Optional[Provider] = Field(
        default=None,
        description="Organization or individual that created this agent",
    )
    cat_version: str = Field(
        default="0.1.0",
        description="Version of Cognitive Agent Tool used to build this agent",
    )

    def skill_ids(self) -> List[str]:
        """Return list of all skill IDs."""
        return [s.id for s in self.skills]

    def get_skill(self, skill_id: str) -> Optional[SkillDefinition]:
        """Find a skill by ID."""
        for skill in self.skills:
            if skill.id == skill_id:
                return skill
        return None
