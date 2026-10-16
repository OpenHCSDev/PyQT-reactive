"""Qt numeric storage is a view; the field member owns null/inherit/absence."""
import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtTest import QTest
from objectstate import Inherit, Unset
from objectstate.field_value import Value
from pyqt_reactive.protocols import SpinBoxAdapter, DoubleSpinBoxAdapter
from pyqt_reactive.widgets.no_scroll_spinbox import NoScrollSpinBox, NoScrollDoubleSpinBox


@pytest.fixture(params=[SpinBoxAdapter, DoubleSpinBoxAdapter, NoScrollSpinBox, NoScrollDoubleSpinBox])
def numeric(qapp, request):
    widget = request.param()
    widget.show()
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_painting_retains_each_member_and_real_minimum_without_input(numeric):
    calls = []
    numeric.connect_change_signal(calls.append)
    for member, expected in [(Inherit(), Inherit()), (Unset(), Unset()), (None, None), (Value(None), None), (Value(7), 7), (0, 0), (numeric.minimum(), numeric.minimum())]:
        numeric.set_value(member)
        assert numeric.get_value() == expected
    assert numeric.specialValueText() == ''
    assert calls == []
    numeric.set_value(None)
    assert numeric.text() == 'None'
    numeric.set_placeholder('Inherited: 77')
    assert numeric.get_value() is None and numeric.text() == 'None'
    numeric.set_value(Inherit())
    assert numeric.text() == 'Inherited: 77'
    assert calls == []


def test_native_typing_admits_zero_once_and_a_real_minimum(numeric):
    numeric.configure_range(-10, 10)
    calls = []
    numeric.connect_change_signal(calls.append)
    for member in (None, Inherit(), Unset()):
        numeric.set_value(member)
        calls.clear()
        numeric.lineEdit().selectAll()
        QTest.keyClicks(numeric.lineEdit(), '0')
        assert numeric.get_value() == 0
        assert calls == [0]
        numeric.set_value(member)
        numeric.lineEdit().selectAll()
        QTest.keyClicks(numeric.lineEdit(), '-10')
        assert numeric.get_value() == -10
        assert numeric.specialValueText() == ''
        assert calls[-1] == -10


def test_native_minimum_is_admitted_when_qt_number_does_not_change(numeric):
    numeric.configure_range(0, 10)
    calls = []
    numeric.connect_change_signal(calls.append)
    for member in (None, Inherit(), Unset()):
        numeric.set_value(member)
        calls.clear()
        assert numeric.value() == 0
        numeric.lineEdit().selectAll()
        QTest.keyClicks(numeric.lineEdit(), '0')
        assert numeric.get_value() == 0
        assert calls == [0]


def test_range_configuration_does_not_commit_null_or_emit_input(numeric):
    calls = []
    numeric.connect_change_signal(calls.append)
    numeric.set_value(None)
    numeric.configure_range(-5, 5)
    assert numeric.get_value() is None and numeric.text() == 'None'
    numeric.blockSignals(True)
    numeric.set_value(Unset())
    numeric.configure_range(-3, 3)
    assert numeric.signalsBlocked()
    numeric.blockSignals(False)
    assert isinstance(numeric.get_value(), Unset)
    assert calls == []
