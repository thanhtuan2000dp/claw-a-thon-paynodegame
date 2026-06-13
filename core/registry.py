"""Auto-discovery registries for use cases and connectors.

Scans the ``usecases`` and ``connectors`` packages, imports every module, and
collects the concrete ``UseCase`` / ``AppDataConnector`` subclasses it finds.
Dropping a new file into either package is all it takes to register it — no
central list to edit.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import TypeVar

T = TypeVar("T")


def _discover(package_name: str, base_cls: type[T]) -> list[type[T]]:
    package = importlib.import_module(package_name)
    found: list[type[T]] = []
    for _, modname, _ in pkgutil.iter_modules(package.__path__):
        if modname.startswith("_") or modname == "base":
            continue
        module = importlib.import_module(f"{package_name}.{modname}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, base_cls)
                and obj is not base_cls
                and obj.__module__ == module.__name__
                and not inspect.isabstract(obj)
            ):
                found.append(obj)
    return found


def discover_use_cases() -> dict[str, type]:
    """name -> UseCase subclass."""
    from usecases.base import UseCase

    return {cls.name: cls for cls in _discover("usecases", UseCase)}


def discover_connector_classes() -> list[type]:
    """All AppDataConnector subclasses (instantiated by core.deps)."""
    from connectors.base import AppDataConnector

    return _discover("connectors", AppDataConnector)
