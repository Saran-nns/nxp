"""Abstract base class for all memory backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List


class BaseMemory(ABC):
    """
    Abstract interface for nxp memory backends.

    All memory implementations must support set/get/delete/clear.
    Additional capabilities (vector search, persistence) are optional.
    """

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Store a value under the given key."""
        ...

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve the value for the given key."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove a key from memory."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Remove all entries from memory."""
        ...

    @abstractmethod
    def keys(self) -> List[str]:
        """Return all keys currently in memory."""
        ...

    def __contains__(self, key: str) -> bool:
        return key in self.keys()
