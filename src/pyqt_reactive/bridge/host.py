"""The main window whose windows, panes and widgets a running-UI bridge introspects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, ClassVar

from formbridge.bridge.identities import UiStableWidgetIdentityDeclaration

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget

    from pyqt_reactive.widgets.shared.dock_layout import DockPanes


class UiBridgeHostWindow:
    """Mixin for an application's main window served by the UI bridge.

    ``window_specs`` maps each managed window id to a spec with ``window_id``
    and ``title``; ``embedded_widgets`` holds the docked panes.
    """

    UI_BRIDGE_WIDGET_IDENTITY: ClassVar[type[UiStableWidgetIdentityDeclaration]]
    embedded_widgets: DockPanes
    window_specs: Mapping[str, object]

    def show_window(self, window_id: str, hide_if_startup: bool = True) -> QWidget:
        """Open or raise one managed window."""

        raise NotImplementedError(f"{type(self).__name__} does not open managed windows.")
