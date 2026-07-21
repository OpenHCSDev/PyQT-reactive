"""Scope-aware table widgets."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QTableWidget, QWidget

from pyqt_reactive.widgets.shared.scope_border_renderer import ScopeBorderRenderer
from pyqt_reactive.widgets.shared.scope_color_receiver import ScopeColorSchemeReceiver
from pyqt_reactive.widgets.shared.scope_visual_config import ScopeColorScheme


class _ScopedTableBorderOverlay(QWidget):
    """Transparent paint surface for scoped table borders."""

    def __init__(self, parent: QTableWidget) -> None:
        super().__init__(parent)
        self._scope_color_scheme: ScopeColorScheme | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_scope_color_scheme(self, scheme: ScopeColorScheme | None) -> None:
        self._scope_color_scheme = scheme
        self.setVisible(scheme is not None and bool(scheme.step_border_layers))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        if self._scope_color_scheme is None:
            return
        painter = QPainter(self)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_Source
        )
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.end()
        ScopeBorderRenderer.paint_border_layers(
            self,
            self._scope_color_scheme,
            self.rect(),
            radius=3,
        )


class ScopedTableWidget(QTableWidget):
    """QTableWidget that paints the shared scoped patterned border."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._base_style_sheet = self.styleSheet()
        self._scope_color_scheme: ScopeColorScheme | None = None
        self._border_overlay = _ScopedTableBorderOverlay(self)
        self._border_overlay.hide()

    def set_scope_color_scheme(self, scheme: ScopeColorScheme | None) -> None:
        """Apply or clear scope-border styling."""

        self._scope_color_scheme = scheme
        if scheme is None or not scheme.step_border_layers:
            self.setStyleSheet(self._base_style_sheet)
            self._border_overlay.set_scope_color_scheme(None)
            self.update()
            return

        border_width = ScopeBorderRenderer.border_width(scheme)
        self.setStyleSheet(
            f"{self._base_style_sheet}\n"
            "QTableWidget { "
            f"border: {border_width}px solid transparent; "
            "border-radius: 3px; "
            "}"
        )
        self._border_overlay.setGeometry(self.rect())
        self._border_overlay.raise_()
        self._border_overlay.set_scope_color_scheme(scheme)
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._border_overlay.setGeometry(self.rect())
        self._border_overlay.raise_()


ScopeColorSchemeReceiver.register(ScopedTableWidget)
