"""Decimal presentation must not expose binary noise or change numeric values."""

import pytest
from PyQt6.QtCore import QLocale, Qt
from PyQt6.QtTest import QTest

from objectstate import Inherit
from pyqt_reactive.protocols import DoubleSpinBoxAdapter
from pyqt_reactive.widgets import NoScrollDoubleSpinBox


@pytest.mark.parametrize("widget_type", [DoubleSpinBoxAdapter, NoScrollDoubleSpinBox])
@pytest.mark.parametrize("locale_name", ["C", "de_DE", "ar_EG"])
@pytest.mark.parametrize("value", [99.8, -99.8, 0.1, 0.0, 255, 1e-12, 1.2345678901234567])
def test_display_and_edit_roundtrip(qapp, widget_type, locale_name, value):
    widget = widget_type()
    widget.setLocale(QLocale(locale_name))
    widget.setDecimals(17)
    widget.set_value(value)
    assert widget.get_value() == float(value)
    assert isinstance(widget.get_value(), float)
    text = widget.cleanText()
    assert widget.locale().toDouble(text) == (float(value), True)
    assert text == widget.locale().toString(
        float(value), "f", QLocale.FloatingPointPrecisionOption.FloatingPointShortest
    )
    assert widget.valueFromText(text) == float(value)
    changes = []
    widget.valueChanged.connect(changes.append)
    widget.lineEdit().setText(text)
    widget.interpretText()
    QTest.keyClick(widget, Qt.Key.Key_Tab)
    assert widget.get_value() == float(value)
    assert changes == []
    widget.close()


def test_decimal_keyboard_entry_and_integer_entry_keep_float_type(qapp):
    widget = NoScrollDoubleSpinBox()
    widget.setLocale(QLocale.c())
    for text, expected in [("99.8", 99.8), ("255", 255.0), ("-0.1", -0.1)]:
        widget.lineEdit().selectAll()
        QTest.keyClicks(widget.lineEdit(), text)
        widget.interpretText()
        assert widget.get_value() == expected
        assert isinstance(widget.get_value(), float)
        assert widget.cleanText() == text


@pytest.mark.parametrize("grouped, expected", [(False, "12345,8"), (True, "12.345,8")])
def test_group_separator_policy_is_preserved(qapp, grouped, expected):
    widget = NoScrollDoubleSpinBox()
    widget.setLocale(QLocale("de_DE"))
    widget.setGroupSeparatorShown(grouped)
    widget.set_value(12345.8)
    assert widget.cleanText() == expected
    assert widget.valueFromText(expected) == 12345.8


def test_placeholder_and_configured_decimal_precision_are_preserved(qapp):
    widget = NoScrollDoubleSpinBox()
    widget.setLocale(QLocale.c())
    widget.set_placeholder("Inherited")
    widget.set_value(Inherit())
    assert isinstance(widget.get_value(), Inherit)
    assert widget.text() == "Inherited"
    widget.set_value(None)
    assert widget.get_value() is None
    assert widget.text() == "None"
    widget.setDecimals(2)
    widget.set_value(1.234)
    assert widget.get_value() == 1.23
    assert widget.cleanText() == "1.23"
