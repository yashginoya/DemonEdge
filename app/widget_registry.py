from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from widgets.base_widget import BaseWidget


@dataclass
class WidgetDefinition:
    widget_id: str
    display_name: str
    category: str
    factory: Callable[[], "BaseWidget"]
    icon: str = ""
    description: str = ""


class _WidgetRegistry:
    """Singleton catalog of all available widget types.

    Widget modules self-register at import time by calling WidgetRegistry.register().
    MainWindow imports all widget modules to trigger registration before building menus.
    """

    _instance: "_WidgetRegistry | None" = None

    def __new__(cls) -> "_WidgetRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._definitions: dict[str, WidgetDefinition] = {}
        return cls._instance

    def register(self, definition: WidgetDefinition) -> None:
        """Register a widget type. Overwrites any previous definition for the same widget_id."""
        self._definitions[definition.widget_id] = definition

    def get_all(self) -> list[WidgetDefinition]:
        return list(self._definitions.values())

    def get_by_category(self) -> dict[str, list[WidgetDefinition]]:
        """Return definitions grouped by category, categories sorted alphabetically,
        entries within each category sorted by display_name."""
        result: dict[str, list[WidgetDefinition]] = {}
        for defn in self._definitions.values():
            result.setdefault(defn.category, []).append(defn)
        for cat in result:
            result[cat].sort(key=lambda d: d.display_name)
        return dict(sorted(result.items()))

    def create(self, widget_id: str) -> "BaseWidget":
        """Instantiate a new widget by widget_id. Raises KeyError if unknown."""
        if widget_id not in self._definitions:
            raise KeyError(f"Unknown widget_id: {widget_id!r}")
        return self._definitions[widget_id].factory()


WidgetRegistry = _WidgetRegistry()
