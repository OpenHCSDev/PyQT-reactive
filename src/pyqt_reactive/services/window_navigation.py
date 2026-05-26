"""Nominal window-navigation capabilities used by pyqt-reactive services."""

from __future__ import annotations

from abc import ABC, abstractmethod

from PyQt6.QtWidgets import QWidget


class ItemNavigableWindow(ABC):
    """Window that can select and reveal an item by identifier."""

    @abstractmethod
    def select_and_scroll_to_item(self, item_id: str) -> None:
        raise NotImplementedError


class FieldNavigableWindow(ABC):
    """Window that can select and reveal a dotted form field path."""

    @abstractmethod
    def select_and_scroll_to_field(self, field_path: str) -> None:
        raise NotImplementedError


class FormManagedWindow(ABC):
    """Window whose root form manager can report build readiness."""

    form_manager: object


class ListNavigationReadinessWindow(ABC):
    """Window or widget with a populated scope-to-list-item navigation index."""

    @property
    @abstractmethod
    def has_list_navigation_items(self) -> bool:
        raise NotImplementedError


class AvoidWidgetsWindow(ABC):
    """Window that declares floating widgets to avoid while positioning."""

    _avoid_widgets: list[QWidget]


class FormNavigationManager(ABC):
    """Form manager surface needed for deferred field navigation."""

    widgets: dict
    nested_managers: dict
    _on_build_complete_callbacks: list
