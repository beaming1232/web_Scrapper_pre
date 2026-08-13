"""
Source registry: auto-discovers every BaseSource subclass in
`scrapers/sources/` so the pipeline never has to know source names in
advance.

Adding a new source requires ZERO changes here — drop a new file in
`scrapers/sources/`, subclass BaseSource, and it will be picked up the
next time `discover_sources()` runs.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Type

from scrapers.base import BaseSource
from scrapers.sources import __name__ as sources_pkg_name
from scrapers.sources import __path__ as sources_pkg_path

_registry: dict[str, Type[BaseSource]] = {}
_discovered = False


def discover_sources(force: bool = False) -> dict[str, Type[BaseSource]]:
    """Import every module under scrapers/sources/ and register BaseSource
    subclasses found within, keyed by their `source_name`.

    Idempotent and cached — safe to call repeatedly. Pass force=True to
    re-scan (useful in tests or after dynamically adding a source file).
    """
    global _discovered

    if _discovered and not force:
        return dict(_registry)

    _registry.clear()

    for module_info in pkgutil.iter_modules(sources_pkg_path):
        if module_info.name.startswith("_"):
            continue

        module = importlib.import_module(f"{sources_pkg_name}.{module_info.name}")

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is BaseSource:
                continue
            if not issubclass(obj, BaseSource):
                continue
            if inspect.isabstract(obj):
                continue
            if obj.__module__ != module.__name__:
                # Skip classes merely imported into this module, not defined
                # in it, to avoid double-registering the same source under
                # multiple module paths.
                continue

            source_name = getattr(obj, "source_name", None)
            if not source_name:
                raise ValueError(
                    f"{obj.__name__} in {module.__name__} must define a "
                    "`source_name` class attribute."
                )
            if source_name in _registry and _registry[source_name] is not obj:
                raise ValueError(
                    f"Duplicate source_name '{source_name}' found in both "
                    f"{_registry[source_name].__module__} and {module.__name__}. "
                    "source_name must be unique."
                )

            _registry[source_name] = obj

    _discovered = True
    return dict(_registry)


def get_source(source_name: str) -> Type[BaseSource]:
    """Look up a single registered source class by name."""
    sources = discover_sources()
    try:
        return sources[source_name]
    except KeyError as exc:
        raise KeyError(
            f"No source registered under '{source_name}'. "
            f"Known sources: {sorted(sources)}"
        ) from exc


def all_sources() -> dict[str, Type[BaseSource]]:
    """Return every registered source class, keyed by source_name."""
    return discover_sources()
