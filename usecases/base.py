"""Use-case contract.

Every capability the agent exposes (UC1 release health, the hypothesis checker,
and later UC2-UC4) is a ``UseCase``. To add one: create a module in this package
with a UseCase subclass — the registry discovers it automatically, the router can
dispatch to it by ``name``, and nothing else needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.deps import Deps


class UseCase(ABC):
    #: stable identifier used as the ``action`` in requests
    name: str = "base"
    #: one-line human description (shown to the LLM router and in help)
    description: str = ""
    #: lightweight {param: description} map for prompting / docs
    input_schema: dict[str, str] = {}

    @abstractmethod
    def run(self, params: dict, deps: "Deps", context=None) -> dict:
        """Execute the use case and return a JSON-serialisable result dict.

        ``context`` carries request metadata (e.g. session_id) for multi-turn use
        cases. Single-shot use cases accept and ignore it.
        """
