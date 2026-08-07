"""Abstract base class for all transports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nxp.agent import Agent


class BaseTransport(ABC):
    """
    Abstract base for all nxp transport implementations.

    To add a new transport, subclass this and implement ``serve()``.
    """

    def __init__(self, agent: "Agent") -> None:
        self.agent = agent

    @abstractmethod
    async def serve(self) -> None:
        """Start the transport server. Should run until cancelled."""
        ...
