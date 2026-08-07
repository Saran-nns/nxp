"""
SessionState — fast, in-process key-value store for agent state.

This is the simplest memory backend: a plain Python dict wrapped in
the BaseMemory interface. Data is not persisted across restarts.

Use this when you need to share state between skill calls within
the same running agent process.

Example
-------
    from nxp import Agent, SessionState

    agent = Agent(name="stateful", description="Remembers things")
    memory = SessionState()

    @agent.skill()
    def remember(key: str, value: str) -> str:
        \"\"\"Store a value in working memory.\"\"\"
        memory.set(key, value)
        return f"Stored '{key}' = '{value}'"

    @agent.skill()
    def recall(key: str) -> str:
        \"\"\"Retrieve a value from working memory.\"\"\"
        return str(memory.get(key, "Not found"))
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from nxp.memory.base import BaseMemory


class SessionState(BaseMemory):
    """
    In-process key-value working memory.

    Thread-safe for concurrent reads; writes use Python's GIL for
    basic safety. For high-concurrency scenarios, add an asyncio.Lock.

    All values are stored as-is (no serialization). Data is lost
    when the process terminates.
    """

    def __init__(self, initial: Optional[Dict[str, Any]] = None) -> None:
        """
        Create a SessionState instance.

        Args:
            initial: Optional initial key-value pairs to pre-populate.
        """
        self._store: Dict[str, Any] = dict(initial or {})

    def set(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key``, overwriting any existing value."""
        self._store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve the value for ``key``.

        Returns ``default`` if the key does not exist.
        """
        return self._store.get(key, default)

    def delete(self, key: str) -> None:
        """Remove ``key`` from memory. No-op if key doesn't exist."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries from memory."""
        self._store.clear()

    def keys(self) -> List[str]:
        """Return a list of all keys currently in memory."""
        return list(self._store.keys())

    def values(self) -> List[Any]:
        """Return all stored values."""
        return list(self._store.values())

    def items(self) -> List[tuple]:
        """Return all (key, value) pairs."""
        return list(self._store.items())

    def update(self, data: Dict[str, Any]) -> None:
        """Merge ``data`` into memory, overwriting existing keys."""
        self._store.update(data)

    def to_dict(self) -> Dict[str, Any]:
        """Return a shallow copy of the memory store as a plain dict."""
        return dict(self._store)

    def __iter__(self) -> Iterator[str]:
        return iter(self._store)

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        return f"SessionState({len(self._store)} keys: {list(self._store.keys())})"


import contextvars
# ContextVar to propagate active session memory to executing skills dynamically
active_session: contextvars.ContextVar[SessionState] = contextvars.ContextVar("active_session")
