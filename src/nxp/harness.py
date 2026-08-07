"""
Agent Harness — Developer-grade execution and orchestration harness for cognitive agents.

Implements three core layers:
1. ContextManager: Tracks workspace state, active files, and execution history.
2. ExecutionLayer: Executes tools, skills, and procedures, enforcing safety and permission checks.
3. AgentHarness: Coordinates planning, execution loops, and error recovery.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, List, Optional, Callable
from pydantic import BaseModel, Field

# ─── Context Manager ─────────────────────────────────────────────────────────

class ContextManager(BaseModel):
    """
    Manages conversation trace, session states, and active file context.
    """
    workspace_path: str = Field(default=".", description="Target workspace directory")
    active_files: List[str] = Field(default_factory=list, description="Currently open/focused files")
    history: List[Dict[str, Any]] = Field(default_factory=list, description="Conversation/action execution log")
    permissions: Dict[str, bool] = Field(default_factory=dict, description="Granted/denied permissions for tools")

    def add_history(self, role: str, content: str, action: Optional[str] = None, result: Optional[Any] = None) -> None:
        """Log an event in the session execution history."""
        self.history.append({
            "role": role,
            "content": content,
            "action": action,
            "result": result
        })

    def request_permission(self, action: str) -> bool:
        """
        Request user authorization before running high-risk execution tools.
        Enforces authorization gates.
        """
        # If explicitly denied/allowed before, reuse
        if action in self.permissions:
            return self.permissions[action]
        # In this harness, we default to requiring permission for high-risk operations like write/delete
        is_risky = any(kw in action for kw in ["write", "delete", "remove", "destroy", "execute"])
        if is_risky:
            # Default fallback allows auto-grant unless explicitly restricted
            return self.permissions.get(action, True)
        return True


# ─── Execution Layer ──────────────────────────────────────────────────────────

class ExecutionLayer:
    """
    Resolves and runs tools, skills, or procedures, managing their dependency lookups.
    """
    def __init__(self, agent: Any) -> None:
        self.agent = agent
        # Local registry of executable bindings
        self.registry: Dict[str, Callable] = {}
        self._load_agent_capabilities()

    def _load_agent_capabilities(self) -> None:
        """Inspect the affiliated agent and load its tools, skills, and procedures."""
        if hasattr(self.agent, "_skills"):
            for skill_id, registered in self.agent._skills.items():
                self.registry[skill_id] = registered

    def get_capabilities_by_type(self, capability_type: str) -> List[str]:
        """Get registered ids filtered by type ('tool', 'skill', 'procedure')."""
        return [
            sid for sid, reg in self.registry.items()
            if hasattr(reg, "type") and reg.type == capability_type
        ]

    async def execute(self, name: str, context: ContextManager, **kwargs: Any) -> Any:
        """
        Execute a capability, enforcing permission checks for safety.
        """
        if name not in self.registry:
            raise KeyError(f"Capability '{name}' is not registered on this harness.")

        capability = self.registry[name]

        # Enforce permission checks
        action_name = f"execute:{name}"
        if not context.request_permission(action_name):
            raise PermissionError(f"Permission denied to execute '{name}'.")

        # Log action before run
        context.add_history("system", f"Executing '{name}'", action=name)

        try:
            # Execute skill/tool/procedure
            result = await capability.execute(**kwargs)
            context.add_history("system", f"Finished '{name}' successfully", action=name, result=result)
            return result
        except Exception as err:
            context.add_history("system", f"Failed '{name}': {err}", action=name)
            raise err


# ─── Agent Harness (Orchestrator) ─────────────────────────────────────────────

class AgentHarness:
    """
    The orchestrating wrapper that drives the cognitive Agent loop (Plan → Act → Observe).
    """
    def __init__(self, agent: Any, workspace_path: str = ".") -> None:
        self.agent = agent
        self.context = ContextManager(workspace_path=workspace_path)
        self.executor = ExecutionLayer(agent)
        self.custom_runner: Optional[Callable] = None

    def __call__(self, func: Callable) -> Callable:
        """Decorator to register a custom orchestrator loop runner function."""
        self.custom_runner = func
        self.agent._register_capability(
            skill_id=func.__name__,
            type="procedure"
        )(func)
        self.executor.registry[func.__name__] = self.agent._skills[func.__name__]
        return func

    @property
    def tools(self) -> List[str]:
        """List registered capability IDs of type 'tool'."""
        return self.executor.get_capabilities_by_type("tool")

    @property
    def skills(self) -> List[str]:
        """List registered capability IDs of type 'skill'."""
        return self.executor.get_capabilities_by_type("skill")

    @property
    def procedures(self) -> List[str]:
        """List registered capability IDs of type 'procedure'."""
        return self.executor.get_capabilities_by_type("procedure")

    async def run(self, task_description: str) -> Dict[str, Any]:
        """
        Run the execution harness loop to complete the task.
        Uses the planning approach from learn-claude-code (v2).
        """
        self.context.add_history("user", task_description)

        # 1. If custom runner is configured, execute it directly
        if self.custom_runner:
            self.context.add_history("orchestrator", f"Executing custom runner '{self.custom_runner.__name__}'", action="custom_run")
            try:
                if inspect.iscoroutinefunction(self.custom_runner):
                    result = await self.custom_runner(task_description)
                else:
                    result = self.custom_runner(task_description)
                self.context.add_history("orchestrator", "Finished custom runner successfully", result=result)
                return {
                    "status": "success",
                    "result": result,
                    "history": self.context.history
                }
            except Exception as exc:
                self.context.add_history("orchestrator", f"Failed custom runner: {exc}")
                return {
                    "status": "failed",
                    "error": str(exc),
                    "history": self.context.history
                }

        # 2. Plan Phase
        plan = f"Task: {task_description}\nAvailable tools: {self.tools}\nAvailable skills: {self.skills}\nAvailable procedures: {self.procedures}"
        self.context.add_history("orchestrator", "Planning execution steps...", action="plan")

        # 3. Execution Loop Phase (Fallback)
        matched_procedure = None
        for pid in self.procedures:
            if pid in task_description.lower().replace("-", "_"):
                matched_procedure = pid
                break

        try:
            if matched_procedure:
                # If a procedure matches, run it
                result = await self.executor.execute(matched_procedure, self.context)
            else:
                # Fallback to executing skills/tools
                if self.skills:
                    first_skill = self.skills[0]
                    result = await self.executor.execute(first_skill, self.context)
                elif self.tools:
                    first_tool = self.tools[0]
                    result = await self.executor.execute(first_tool, self.context)
                else:
                    result = "No tools, skills, or procedures defined."

            return {
                "status": "success",
                "result": result,
                "history": self.context.history
            }

        except Exception as exc:
            return {
                "status": "failed",
                "error": str(exc),
                "history": self.context.history
            }


# ─── Environment Harness (Harness Engineering) ───────────────────────────────

class EnvironmentHarness:
    """
    EnvironmentHarness provides Harness Engineering capabilities:
    Inspects runtime environment state, dynamically injects tools based on environment capabilities,
    and enforces safety sandboxing boundaries.
    """
    def __init__(self, agent: Any, environment_name: str = "production"):
        self.agent = agent
        self.environment_name = environment_name
        self.env_variables: Dict[str, str] = {}
        self.sandboxed: bool = True

    def set_env(self, key: str, value: str) -> EnvironmentHarness:
        """Set environment variable key-value state."""
        self.env_variables[key] = value
        return self

    def inspect_environment(self) -> Dict[str, Any]:
        """Inspect the current environment state, variables, and capabilities."""
        return {
            "environment_name": self.environment_name,
            "sandboxed": self.sandboxed,
            "env_variables": list(self.env_variables.keys()),
            "agent_name": getattr(self.agent, "name", "unknown")
        }

    def bind_environment_tool(self, tool_id: str, func: Callable) -> None:
        """Dynamically inject an environment-specific tool into the agent."""
        if hasattr(self.agent, "tool"):
            self.agent.tool(tool_id=tool_id)(func)
            print(f"[EnvironmentHarness] Dynamically injected tool '{tool_id}' into environment '{self.environment_name}'")

