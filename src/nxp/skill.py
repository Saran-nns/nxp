"""
Skill registry and schema extraction.

This module handles:
- Auto-generating JSON Schema from Python type hints and default values
- Wrapping sync functions in async-safe executors
- The RegisteredSkill container that holds a callable + its metadata
"""

from __future__ import annotations

import inspect
import typing
from typing import Any, Callable, Dict, List, Optional, get_type_hints

from nxp.card import SkillDefinition



# ─── Type → JSON Schema Mapping ────────────────────────────────────────────────

_PY_TO_JSON: Dict[Any, Dict[str, str]] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    bytes: {"type": "string", "format": "byte"},
}


def _type_to_schema(annotation: Any) -> Dict[str, Any]:
    """
    Recursively convert a Python type annotation to a JSON Schema dict.

    Handles:
      - Primitives: str, int, float, bool, bytes
      - Optional[X]  →  {nullable: true, ...X schema}
      - List[X]      →  {type: array, items: ...X schema}
      - Dict[K, V]   →  {type: object}
      - Union[X, Y]  →  {anyOf: [...]}
      - Any / unknown → {type: string}  (safe fallback)
    """
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {"type": "string"}

    if annotation in _PY_TO_JSON:
        return dict(_PY_TO_JSON[annotation])

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    # Optional[X] = Union[X, None]
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            schema = _type_to_schema(non_none[0])
            schema["nullable"] = True
            return schema
        return {"anyOf": [_type_to_schema(a) for a in non_none]}

    # List[X]
    if origin is list:
        item_type = args[0] if args else Any
        return {"type": "array", "items": _type_to_schema(item_type)}

    # Dict[K, V]
    if origin is dict:
        return {"type": "object"}

    # Tuple, Set, etc. → array
    if origin in (tuple, set, frozenset):
        return {"type": "array"}

    # Pydantic model / dataclass → object
    if hasattr(annotation, "model_json_schema"):
        return annotation.model_json_schema()

    # Fallback
    return {"type": "string"}


def _extract_param_schema(func: Callable) -> Dict[str, Any]:
    """
    Build a JSON Schema "object" for all parameters of a function.

    Example:
        def search(query: str, limit: int = 10) -> str: ...
        → {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["query"]
          }
    """
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    hints.pop("return", None)
    sig = inspect.signature(func)

    properties: Dict[str, Any] = {}
    required: List[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls", "memory"):
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        annotation = hints.get(param_name, Any)
        schema = _type_to_schema(annotation)

        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            # Serialize default safely
            default = param.default
            if default is not None and not isinstance(default, (str, int, float, bool, list, dict)):
                default = str(default)
            schema["default"] = default

        properties[param_name] = schema

    result: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        result["required"] = required

    return result


# ─── RegisteredSkill ────────────────────────────────────────────────────────────


class RegisteredSkill:
    """
    A skill registered on an Agent.

    Wraps a Python callable with:
    - Skill metadata (id, name, description, tags, examples)
    - Auto-generated JSON Schema for its parameters
    - Async-safe execution (sync functions run in thread pool)
    """

    def __init__(
        self,
        func: Callable,
        skill_id: str,
        name: str,
        description: str,
        tags: List[str],
        examples: List[str],
        input_modes: List[str],
        output_modes: List[str],
        transports: Optional[List[str]] = None,
        type: str = "skill",
    ) -> None:
        self.func = func
        self.skill_id = skill_id
        self.name = name
        self.description = description
        self.tags = tags
        self.examples = examples
        self.input_modes = input_modes
        self.output_modes = output_modes
        self.transports = transports  # None = all transports
        self.type = type
        self.is_async = inspect.iscoroutinefunction(func)
        self.param_schema = _extract_param_schema(func)

    async def execute(self, **kwargs: Any) -> Any:
        """
        Execute the skill.

        Auto-injects session-scoped memory if expected by signature.
        Async functions are awaited directly.
        Sync functions are dispatched to anyio's thread pool.
        """
        # ── Auto-inject memory context if signature expects it ──────
        sig = inspect.signature(self.func)
        if "memory" in sig.parameters and "memory" not in kwargs:
            from nxp.memory.session import active_session
            mem_val = active_session.get(None)
            if mem_val is not None:
                kwargs["memory"] = mem_val

        # ── Execute (sync or async) ───────────────────────────────
        if self.is_async:
            return await self.func(**kwargs)
        else:
            import anyio
            return await anyio.to_thread.run_sync(lambda: self.func(**kwargs))

    def to_skill_definition(self) -> SkillDefinition:
        """Convert to an A2A-compatible SkillDefinition."""
        return SkillDefinition(
            id=self.skill_id,
            name=self.name,
            description=self.description,
            tags=self.tags,
            examples=self.examples,
            input_modes=self.input_modes,
            output_modes=self.output_modes,
            parameters=self.param_schema,
            type=self.type,
        )

    def __repr__(self) -> str:
        return (
            f"RegisteredSkill(id={self.skill_id!r}, "
            f"async={self.is_async}, "
            f"params={list(self.param_schema.get('properties', {}).keys())})"
        )
