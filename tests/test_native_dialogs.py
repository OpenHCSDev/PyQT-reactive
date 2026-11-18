"""Native file dialogs: off on desktops (the theme paints Qt's own), on where the
system's picker is the only way into the device's storage."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pyqt_reactive.theming.color_scheme import ColorScheme
from pyqt_reactive.theming.palette_manager import ThemeManager


def test_phones_keep_the_system_picker():
    assert ThemeManager.native_dialogs_required("android")
    assert ThemeManager.native_dialogs_required("ios")


def test_desktops_use_the_themed_dialog():
    for name in ("xcb", "wayland", "windows", "cocoa", "offscreen", ""):
        assert not ThemeManager.native_dialogs_required(name)


def test_applying_a_scheme_on_a_desktop_platform_selects_the_themed_dialog():
    QApplication.instance() or QApplication([])
    ThemeManager(ColorScheme()).apply_color_scheme(ColorScheme())
    assert QApplication.testAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
