"""A splitter child that can be shown, hidden, or moved into its own window."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QPushButton, QSplitter, QVBoxLayout, QWidget

from pyqt_reactive.theming import ColorScheme


class PanelPlacement(ABC):
    """Where a detachable panel's widget currently lives."""

    @abstractmethod
    def set_shown(self, panel: DetachablePanel, shown: bool) -> None:
        """Show or hide the widget where it lives."""

    @abstractmethod
    def detached(self, panel: DetachablePanel) -> PanelPlacement:
        """The placement after a detach request."""

    @abstractmethod
    def reattached(self, panel: DetachablePanel) -> PanelPlacement:
        """The placement after a reattach request."""


@dataclass(frozen=True)
class Docked(PanelPlacement):
    """The widget sits in its splitter."""

    def set_shown(self, panel: DetachablePanel, shown: bool) -> None:
        panel.widget.setVisible(shown)

    def detached(self, panel: DetachablePanel) -> PanelPlacement:
        window = _FloatingPanelWindow(panel)
        panel.widget.setParent(window)
        window.layout().addWidget(panel.widget)
        panel.widget.setVisible(True)
        window.show()
        return Floating(window)

    def reattached(self, panel: DetachablePanel) -> PanelPlacement:
        return self


@dataclass(frozen=True)
class Floating(PanelPlacement):
    """The widget sits in its own window."""

    window: QDialog

    def set_shown(self, panel: DetachablePanel, shown: bool) -> None:
        self.window.setVisible(shown)

    def detached(self, panel: DetachablePanel) -> PanelPlacement:
        self.window.show()
        self.window.raise_()
        return self

    def reattached(self, panel: DetachablePanel) -> PanelPlacement:
        panel.widget.setParent(panel.splitter)
        panel.splitter.insertWidget(panel.index, panel.widget)
        panel.widget.setVisible(panel.is_shown)
        self.window.hide()
        self.window.deleteLater()
        return Docked()


class _FloatingPanelWindow(QDialog):
    """The window a detached panel floats in; closing it reattaches the panel."""

    def __init__(self, panel: DetachablePanel) -> None:
        super().__init__(panel.splitter.window())
        self._panel = panel
        self.setWindowTitle(panel.title)
        self.setWindowFlags(Qt.WindowType.Dialog)
        self.setMinimumSize(600, 400)
        self.resize(800, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        reattach_button = QPushButton("⬅ Reattach to Main Window")
        reattach_button.setStyleSheet(panel.color_scheme.styles.generate_button_style())
        reattach_button.clicked.connect(panel.reattach)
        layout.addWidget(reattach_button)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        self._panel.reattach()
        event.accept()


class DetachablePanel(QObject):
    """Owns one optional panel of a splitter and the button that toggles it.

    The widget starts hidden at ``index`` of ``splitter``. ``toggle_button``
    shows and hides it; :meth:`detach` moves it into its own window and
    :meth:`reattach` (or closing that window) moves it back.
    """

    shown = pyqtSignal()
    """Emitted when the panel becomes visible, so its owner can fill it."""

    def __init__(
        self,
        widget: QWidget,
        splitter: QSplitter,
        index: int,
        title: str,
        color_scheme: ColorScheme | None = None,
    ) -> None:
        super().__init__(splitter)
        self.widget = widget
        self.splitter = splitter
        self.index = index
        self.title = title
        self.color_scheme = color_scheme or ColorScheme()
        self.placement: PanelPlacement = Docked()
        self.toggle_button = QPushButton()
        self.toggle_button.setCheckable(True)
        self.toggle_button.setStyleSheet(self.color_scheme.styles.generate_button_style())
        self.toggle_button.toggled.connect(self._set_shown)
        splitter.insertWidget(index, widget)
        self._set_shown(False)

    @property
    def is_shown(self) -> bool:
        return self.toggle_button.isChecked()

    def _set_shown(self, shown: bool) -> None:
        self.toggle_button.setText(f"{'Hide' if shown else 'Show'} {self.title}")
        self.placement.set_shown(self, shown)
        if shown:
            self.shown.emit()

    def detach(self) -> None:
        self.placement = self.placement.detached(self)

    def reattach(self) -> None:
        self.placement = self.placement.reattached(self)
