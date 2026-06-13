"""Output channel contract.

An output turns a use-case result dict into something a human consumes — markdown
text now, a Teams/Slack webhook push later (UC2/UC4). Use cases return structured
dicts; outputs decide presentation/delivery.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class OutputChannel(ABC):
    name: str = "base"

    @abstractmethod
    def render(self, result: dict) -> str:
        """Return a presentation string for the given result."""
