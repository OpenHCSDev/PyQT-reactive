"""Tests for theming system."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QLabel,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollBar,
    QSplitter,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from pyqt_reactive.theming import ColorScheme


class _DerivedTabBar(QTabBar):
    """Representative docking/log-viewer tab subclass."""


class _DerivedDialog(QDialog):
    """Representative application dialog subclass."""


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
    from pyqt_reactive.theming import ColorScheme

    scheme = ColorScheme()
    stylesheet = scheme.styles.generate_complete_application_style()

    assert "QMenuBar {" in stylesheet
    assert "QMenu {" in stylesheet
    assert "QScrollBar:vertical, QScrollBar:horizontal" in stylesheet
    assert "QScrollBar::handle:vertical" in stylesheet
    assert "QScrollBar::handle:horizontal" in stylesheet
    assert "QTabWidget::pane" in stylesheet
    assert "QTabBar::tab" in stylesheet
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
    from pyqt_reactive.theming import ThemeManager

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


@pytest.mark.parametrize(
    "orientation",
    (Qt.Orientation.Horizontal, Qt.Orientation.Vertical),
)
def test_theme_manager_renders_splitter_grip_without_changing_geometry(
    qapp,
    orientation,
):
    """The shared style supplies visible grip dots without resizing handles."""
    from pyqt_reactive.theming import ColorScheme, ThemeManager

    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    splitter = QSplitter(orientation)
    splitter.addWidget(QLabel("First"))
    splitter.addWidget(QLabel("Second"))
    splitter.resize(180, 60)
    splitter.show()
    qapp.processEvents()

    handle = splitter.handle(1)
    baseline_handle_size = handle.size()
    try:
        scheme = ColorScheme()
        ThemeManager(scheme).apply_color_scheme(scheme)
        qapp.processEvents()

        assert handle.size() == baseline_handle_size
        image = handle.grab().toImage()
        center = image.rect().center()
        grip_color = scheme.to_hex(scheme.border_color)
        for offset in (-6, -3, 0, 3, 6):
            if orientation is Qt.Orientation.Horizontal:
                pixel = image.pixelColor(center.x(), center.y() + offset)
            else:
                pixel = image.pixelColor(center.x() + offset, center.y())
            assert pixel.name() == grip_color
    finally:
        splitter.close()
        qapp.setStyleSheet(original_stylesheet)
        qapp.setPalette(original_palette)


def test_splitter_grip_style_is_application_owned_and_idempotent(qapp):
    """Repeated theme application reuses one proxy and preserves application QSS."""
    from pyqt_reactive.theming import ColorScheme, ThemeManager
    from pyqt_reactive.theming.splitter_grip_style import (
        install_application_control_style,
    )

    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    try:
        scheme = ColorScheme()
        manager = ThemeManager(scheme)
        manager.apply_color_scheme(scheme)
        installed = install_application_control_style(qapp)
        application_stylesheet = qapp.styleSheet()

        manager.apply_color_scheme(scheme)

        assert install_application_control_style(qapp) is installed
        assert qapp.styleSheet() == application_stylesheet
        assert application_stylesheet == manager.get_application_control_style_sheet()
    finally:
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

        assert (
            qapp.styleSheet()
            == theme_manager.get_application_control_style_sheet()
        )
        assert theme_manager.get_native_control_style_sheet() in qapp.styleSheet()
        assert "QPushButton {" in qapp.styleSheet()
        assert "border: none;" in qapp.styleSheet()
        assert "QGroupBox" not in qapp.styleSheet()
        assert "QDialog, QMessageBox, QFileDialog" in qapp.styleSheet()
        assert "QToolTip {" in qapp.styleSheet()
        assert "QComboBox QAbstractItemView" in qapp.styleSheet()
        assert "QProgressBar::chunk" in qapp.styleSheet()
        assert "QCheckBox {" in qapp.styleSheet()
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


@pytest.mark.parametrize(
    "scheme_factory",
    (ColorScheme, ColorScheme.create_light_theme),
)
def test_theme_manager_colors_native_form_controls_without_geometry_rules(
    qapp,
    scheme_factory,
):
    """Windows-sensitive inputs use theme colors without shared layout QSS."""

    from pyqt_reactive.theming import ThemeManager

    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    combo = QComboBox()
    progress = QProgressBar()
    checkbox = QCheckBox("Enabled")
    try:
        scheme = scheme_factory()
        manager = ThemeManager(scheme)
        manager.apply_color_scheme(scheme)
        combo.addItems(["First", "Second"])
        progress.setRange(0, 100)
        progress.setValue(50)
        checkbox.setChecked(True)
        for widget in (combo, progress, checkbox):
            widget.resize(180, 30)
            widget.show()
        qapp.processEvents()

        stylesheet = manager.get_application_control_style_sheet()
        assert scheme.to_hex(scheme.input_bg) in stylesheet
        assert scheme.to_hex(scheme.progress_bg) in stylesheet
        assert scheme.to_hex(scheme.progress_fill) in stylesheet
        native_form_style = (
            manager.color_scheme.styles.generate_native_form_control_color_style()
        )
        assert "padding:" not in native_form_style
        assert "min-height:" not in stylesheet
        assert "min-width:" not in stylesheet

        checkbox_colors = {
            checkbox.grab().toImage().pixelColor(x, y).name()
            for x in range(checkbox.width())
            for y in range(checkbox.height())
        }
        assert scheme.to_hex(scheme.button_normal_bg) in checkbox_colors
        assert scheme.to_hex(scheme.selection_bg) not in checkbox_colors
    finally:
        combo.close()
        progress.close()
        checkbox.close()
        qapp.setStyleSheet(original_stylesheet)
        qapp.setPalette(original_palette)


def test_theme_manager_renders_tab_bar_from_color_scheme(qapp):
    """Application tabs inherit the shared theme instead of OS white defaults."""

    from pyqt_reactive.theming import ColorScheme, ThemeManager

    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    tab_bar = _DerivedTabBar()
    try:
        scheme = ColorScheme()
        theme_manager = ThemeManager(scheme)
        theme_manager.apply_color_scheme(scheme)
        tab_bar.addTab("First")
        tab_bar.addTab("Second")
        tab_bar.setCurrentIndex(0)
        tab_bar.resize(240, 32)
        tab_bar.show()
        qapp.processEvents()

        stylesheet = theme_manager.get_native_control_style_sheet()
        assert "QTabBar::tab" in stylesheet
        assert scheme.to_hex(scheme.panel_bg) in stylesheet
        assert scheme.to_hex(scheme.button_normal_bg) in stylesheet

        image = tab_bar.grab().toImage()
        rendered_colors = {
            image.pixelColor(x, y).name()
            for x in range(image.width())
            for y in range(image.height())
        }
        assert scheme.to_hex(scheme.panel_bg) in rendered_colors
        assert scheme.to_hex(scheme.button_normal_bg) in rendered_colors
    finally:
        tab_bar.close()
        qapp.setStyleSheet(original_stylesheet)
        qapp.setPalette(original_palette)


def test_theme_manager_selects_inherited_qt_file_dialogs(qapp):
    """The shared theme prevents native dialogs from bypassing application QSS."""

    from pyqt_reactive.theming import ColorScheme, ThemeManager

    attribute = Qt.ApplicationAttribute.AA_DontUseNativeDialogs
    original_value = QApplication.testAttribute(attribute)
    try:
        QApplication.setAttribute(attribute, False)
        scheme = ColorScheme()
        ThemeManager(scheme).apply_color_scheme(scheme)

        assert QApplication.testAttribute(attribute)
    finally:
        QApplication.setAttribute(attribute, original_value)


def test_theme_manager_renders_all_dialog_subclasses_from_shared_colors(qapp):
    """Application, message, and file dialogs share one inherited color rule."""

    from pyqt_reactive.theming import ColorScheme, ThemeManager

    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    dialogs = (_DerivedDialog(), QMessageBox())
    try:
        scheme = ColorScheme()
        ThemeManager(scheme).apply_color_scheme(scheme)
        for dialog in dialogs:
            dialog.resize(240, 120)
            dialog.show()
        qapp.processEvents()

        expected_background = scheme.to_hex(scheme.window_bg)
        assert "QFileDialog" in qapp.styleSheet()
        for dialog in dialogs:
            rendered_colors = {
                dialog.grab().toImage().pixelColor(x, y).name()
                for x in range(dialog.width())
                for y in range(dialog.height())
            }
            assert expected_background in rendered_colors
    finally:
        for dialog in dialogs:
            dialog.close()
        qapp.setStyleSheet(original_stylesheet)
        qapp.setPalette(original_palette)


def test_theme_manager_renders_message_box_buttons_from_shared_style(qapp):
    """Updater-style message boxes inherit the borderless button authority."""
    from pyqt_reactive.theming import ColorScheme, ThemeManager

    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    message_box = QMessageBox()
    try:
        scheme = ColorScheme()
        ThemeManager(scheme).apply_color_scheme(scheme)
        message_box.setWindowTitle("OpenHCS Update Available")
        message_box.setText("Install the update now?")
        message_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        message_box.setDefaultButton(QMessageBox.StandardButton.Yes)
        message_box.show()
        qapp.processEvents()

        yes_button = message_box.button(QMessageBox.StandardButton.Yes)
        cancel_button = message_box.button(QMessageBox.StandardButton.Cancel)
        assert isinstance(yes_button, QPushButton)
        assert isinstance(cancel_button, QPushButton)
        assert yes_button.styleSheet() == ""
        assert cancel_button.styleSheet() == ""

        rendered_colors = {
            yes_button.grab().toImage().pixelColor(x, y).name()
            for x in range(yes_button.width())
            for y in range(yes_button.height())
        }
        assert scheme.to_hex(scheme.button_normal_bg) in rendered_colors
    finally:
        message_box.close()
        qapp.setStyleSheet(original_stylesheet)
        qapp.setPalette(original_palette)


def test_qscintilla_editor_uses_shared_borderless_button_style(qapp, monkeypatch):
    """The code editor must not restore its former outlined button mirror."""
    from types import SimpleNamespace

    from pyqt_reactive.theming import ColorScheme, ThemeManager
    from pyqt_reactive.widgets import llm_chat_panel
    from pyqt_reactive.widgets.editors.simple_code_editor import (
        QSCINTILLA_AVAILABLE,
        QScintillaCodeEditorDialog,
    )

    if not QSCINTILLA_AVAILABLE:
        pytest.skip("QScintilla is not installed")

    original_palette = QPalette(qapp.palette())
    original_stylesheet = qapp.styleSheet()
    monkeypatch.setattr(
        llm_chat_panel,
        "get_llm_service",
        lambda: SimpleNamespace(test_connection=lambda: True),
    )
    dialog = None
    try:
        scheme = ColorScheme()
        ThemeManager(scheme).apply_color_scheme(scheme)
        dialog = QScintillaCodeEditorDialog(None, "x = 1", "Edit Pipeline")
        dialog.show()
        qapp.processEvents()

        shared_button_style = scheme.styles.generate_button_style()
        assert shared_button_style in dialog.styleSheet()
        former_outline = (
            f"border: 1px solid {scheme.to_hex(scheme.border_light)}"
        )
        assert former_outline not in dialog.styleSheet()
        for button in (dialog.llm_assist_btn, dialog.save_btn, dialog.cancel_btn):
            assert button.styleSheet() == ""
            rendered_colors = {
                button.grab().toImage().pixelColor(x, y).name()
                for x in range(button.width())
                for y in range(button.height())
            }
            assert scheme.to_hex(scheme.button_normal_bg) in rendered_colors
    finally:
        if dialog is not None:
            dialog.close()
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
