"""
Declarative class and method decorators for NXP Agents.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, List, Optional

def tool(
    *,
    tool_id: Optional[str] = None,
    name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    examples: Optional[List[str]] = None,
    input_modes: Optional[List[str]] = None,
    output_modes: Optional[List[str]] = None,
    transports: Optional[List[str]] = None,
) -> Callable:
    """Decorator to mark a class method as a deterministic tool."""
    def decorator(func: Callable) -> Callable:
        func._nxp_capability = {
            "type": "tool",
            "kwargs": {
                "skill_id": tool_id,
                "name": name,
                "tags": tags,
                "examples": examples,
                "input_modes": input_modes,
                "output_modes": output_modes,
                "transports": transports,
            }
        }
        return func
    return decorator

def skill(
    *,
    skill_id: Optional[str] = None,
    name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    examples: Optional[List[str]] = None,
    input_modes: Optional[List[str]] = None,
    output_modes: Optional[List[str]] = None,
    transports: Optional[List[str]] = None,
) -> Callable:
    """Decorator to mark a class method as a reasoning skill."""
    def decorator(func: Callable) -> Callable:
        func._nxp_capability = {
            "type": "skill",
            "kwargs": {
                "skill_id": skill_id,
                "name": name,
                "tags": tags,
                "examples": examples,
                "input_modes": input_modes,
                "output_modes": output_modes,
                "transports": transports,
            }
        }
        return func
    return decorator

def procedure(
    *,
    procedure_id: Optional[str] = None,
    name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    examples: Optional[List[str]] = None,
    input_modes: Optional[List[str]] = None,
    output_modes: Optional[List[str]] = None,
    transports: Optional[List[str]] = None,
) -> Callable:
    """Decorator to mark a class method as a multi-step procedure."""
    def decorator(func: Callable) -> Callable:
        func._nxp_capability = {
            "type": "procedure",
            "kwargs": {
                "skill_id": procedure_id,
                "name": name,
                "tags": tags,
                "examples": examples,
                "input_modes": input_modes,
                "output_modes": output_modes,
                "transports": transports,
            }
        }
        return func
    return decorator

def harness(
    *,
    harness_id: Optional[str] = None,
    name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    examples: Optional[List[str]] = None,
    input_modes: Optional[List[str]] = None,
    output_modes: Optional[List[str]] = None,
    transports: Optional[List[str]] = None,
) -> Callable:
    """Decorator to mark a class method as a custom harness orchestrator."""
    def decorator(func: Callable) -> Callable:
        func._nxp_capability = {
            "type": "harness",
            "kwargs": {
                "skill_id": harness_id,
                "name": name,
                "tags": tags,
                "examples": examples,
                "input_modes": input_modes,
                "output_modes": output_modes,
                "transports": transports,
            }
        }
        return func
    return decorator

def agent(
    name: Optional[str] = None,
    description: Optional[str] = None,
    harness: bool = False,
    **agent_kwargs: Any,
) -> Callable:
    """
    Class decorator to convert a standard class into a fully featured NXP Agent.
    """
    def decorator(cls: type) -> type:
        from nxp.agent import Agent

        agent_name = name or cls.__name__
        agent_desc = description or cls.__doc__ or agent_name

        class DecoratedAgent(Agent, cls):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                # Initialize NXP Agent base
                Agent.__init__(
                    self,
                    name=agent_name,
                    description=agent_desc,
                    **agent_kwargs
                )
                # Initialize user class
                cls.__init__(self, *args, **kwargs)

                # Scan and register marked methods
                for attr_name in dir(self):
                    attr = getattr(self, attr_name, None)
                    if attr and hasattr(attr, "__func__") and hasattr(attr.__func__, "_nxp_capability"):
                        cap = attr.__func__._nxp_capability
                        if cap["type"] == "harness":
                            self.harness()(attr)
                        else:
                            self._register_capability(
                                skill_id=cap["kwargs"].get("skill_id") or attr_name,
                                name=cap["kwargs"].get("name"),
                                tags=cap["kwargs"].get("tags"),
                                examples=cap["kwargs"].get("examples"),
                                input_modes=cap["kwargs"].get("input_modes"),
                                output_modes=cap["kwargs"].get("output_modes"),
                                transports=cap["kwargs"].get("transports"),
                                type=cap["type"]
                            )(attr)

                if harness and not hasattr(self, "_harness"):
                    self.harness()

        DecoratedAgent.__name__ = cls.__name__
        DecoratedAgent.__doc__ = cls.__doc__
        return DecoratedAgent
    return decorator
