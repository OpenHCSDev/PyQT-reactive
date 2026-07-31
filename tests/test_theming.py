"""Tests for theming system."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QGroupBox,
    QLabel,
    QMenuBar,
    QScrollBar,
    QVBoxLayout,
    QWidget,
)


def test_color_scheme_creation():
    """Test ColorScheme instantiation."""
    from pyqt_reactive.theming import ColorScheme

    scheme = ColorScheme()
    assert scheme is not None
    assert hasattr(scheme, 'to_hex')


def test_palette_manager(qapp):
    """Test PaletteManager creation."""
    from pyqt_reactive.theming import ColorScheme, PaletteManager

    scheme = ColorScheme()
    manager = PaletteManager(scheme)
    assert manager is not None


def test_complete_application_style_owns_native_menu_and_scrollbar_colors():
    """The application theme, rather than individual widgets, owns native chrome."""
    from pyqt_reactive.theming import ColorScheme, StyleSheetGenerator

    scheme = ColorScheme()
    stylesheet = StyleSheetGenerator(scheme).generate_complete_application_style()

    assert "QMenuBar {" in stylesheet
    assert "QMenu {" in stylesheet
    assert "QScrollBar:vertical, QScrollBar:horizontal" in stylesheet
    assert "QScrollBar::handle:vertical" in stylesheet
    assert "QScrollBar::handle:horizontal" in stylesheet
    assert scheme.to_hex(scheme.panel_bg) in stylesheet
    assert scheme.to_hex(scheme.button_normal_bg) in stylesheet


@pytest.mark.parametrize(
    ("orientation", "size"),
    (
        (Qt.Orientation.Vertical, (24, 180)),
        (Qt.Orientation.Horizontal, (180, 24)),
    ),
)
def test_theme_manager_renders_both_scrollbar_orientations_from_color_scheme(
    qapp,
    orientation,
    size,
):
    """Both native scrollbar orientations render with the declared dark colors."""
    from pyqt_reactive.theming import ColorScheme, ThemeManager

    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    scrollbar = QScrollBar(orientation)
    try:
        scheme = ColorScheme()
        ThemeManager(scheme).apply_color_scheme(scheme)
        scrollbar.setRange(0, 100)
        scrollbar.setPageStep(20)
        scrollbar.setValue(40)
        scrollbar.resize(*size)
        scrollbar.show()
        qapp.processEvents()

        image = scrollbar.grab().toImage()
        rendered_colors = {
            image.pixelColor(x, y).name()
            for x in range(image.width())
            for y in range(image.height())
        }
        assert scheme.to_hex(scheme.panel_bg) in rendered_colors
        assert scheme.to_hex(scheme.button_normal_bg) in rendered_colors
    finally:
        scrollbar.close()
        qapp.setStyleSheet(original_stylesheet)
        qapp.setPalette(original_palette)


def test_theme_manager_renders_menu_bar_from_color_scheme(qapp):
    """Application-level theming keeps the menu bar out of the OS white theme."""
    from pyqt_reactive.theming import ColorScheme, ThemeManager

    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    menu_bar = QMenuBar()
    try:
        scheme = ColorScheme()
        theme_manager = ThemeManager(scheme)
        theme_manager.apply_color_scheme(scheme)
        menu_bar.addMenu("File")
        menu_bar.resize(220, 30)
        menu_bar.show()
        qapp.processEvents()

        assert qapp.styleSheet() == theme_manager.get_native_control_style_sheet()
        assert "QGroupBox" not in qapp.styleSheet()
        assert "QDialog" not in qapp.styleSheet()
        assert "padding:" not in qapp.styleSheet()
        assert "margin:" not in qapp.styleSheet()
        assert "min-height:" not in qapp.styleSheet()
        assert "min-width:" not in qapp.styleSheet()
        image = menu_bar.grab().toImage()
        rendered_colors = {
            image.pixelColor(x, y).name()
            for x in range(image.width())
            for y in range(image.height())
        }
        assert scheme.to_hex(scheme.panel_bg) in rendered_colors
    finally:
        menu_bar.close()
        qapp.setStyleSheet(original_stylesheet)
        qapp.setPalette(original_palette)


def test_native_control_theme_preserves_nested_widget_geometry(qapp):
    """Coloring native chrome must not alter nested form spacing or size hints."""
    from pyqt_reactive.theming import ColorScheme, ThemeManager

    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    root = QWidget()
    outer_layout = QVBoxLayout(root)
    outer_group = QGroupBox("Outer")
    outer_layout.addWidget(outer_group)
    inner_layout = QVBoxLayout(outer_group)
    inner_group = QGroupBox("Inner")
    inner_layout.addWidget(inner_group)
    leaf_layout = QVBoxLayout(inner_group)
    leaf_layout.addWidget(QLabel("Value"))
    try:
        qapp.setStyleSheet("")
        root.ensurePolished()
        qapp.processEvents()
        baseline_size_hint = root.sizeHint()
        baseline_layout_metrics = tuple(
            (layout.contentsMargins(), layout.spacing())
            for layout in (outer_layout, inner_layout, leaf_layout)
        )

        scheme = ColorScheme()
        ThemeManager(scheme).apply_color_scheme(scheme)
        root.ensurePolished()
        qapp.processEvents()

        assert root.sizeHint() == baseline_size_hint
        assert tuple(
            (layout.contentsMargins(), layout.spacing())
            for layout in (outer_layout, inner_layout, leaf_layout)
        ) == baseline_layout_metrics
    finally:
        root.close()
        qapp.setStyleSheet(original_stylesheet)
        qapp.setPalette(original_palette)
