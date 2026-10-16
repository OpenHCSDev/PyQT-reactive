"""Native controls consume admitted fields; painting and reset do not double-edit."""
from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from objectstate import FieldAccessError, Inherit, LazyDataclassFactory, ObjectState, Unset, set_base_config_type, set_global_config
from PyQt6.QtCore import QEvent, QEventLoop, QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLineEdit

from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager
from pyqt_reactive.services.signal_service import SignalService


@contextmanager
def shown_form(app):
    @dataclass
    class Nested:
        enabled: bool | None = True
        text: str = 'nested'
    @dataclass
    class Settings:
        enabled: bool | None = True
        text: str | None = None
        count: int | None = 4
        nested: Nested = field(default_factory=Nested)
    set_base_config_type(Settings)
    set_global_config(Settings, Settings(text='global text', count=77))
    lazy = LazyDataclassFactory.make_lazy_simple(Settings)
    state = ObjectState(lazy(text=None, nested=Nested()), scope_id='declared-fields-form-test')
    manager = ParameterFormManager(state)
    try:
        if not manager.form_build_complete:
            built, deadline = QEventLoop(), QTimer()
            deadline.setSingleShot(True)
            deadline.timeout.connect(built.quit)
            manager.register_form_build_completion_callback(built.quit)
            manager.form_build_failed.connect(lambda _error: built.quit())
            try:
                deadline.start(2000)
                built.exec()
            finally:
                deadline.stop()
        assert manager.form_build_failure is None, manager.form_build_failure
        assert manager.form_build_complete
        manager.show()
        app.processEvents()
        yield state, manager
    finally:
        manager.dispose()
        manager.close()
        manager.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert state._on_state_changed_callbacks == []
        assert state._on_resolved_changed_callbacks == []


def test_open_form_preserves_null_absence_and_inheritance(qapp):
    with shown_form(qapp) as (state, manager):
        text, count = manager.widgets['text'], manager.widgets['count']
        assert text.get_value() is None
        assert isinstance(count.get_value(), Inherit)
        assert state.fields.count.value == 77
        assert isinstance(manager._widget_service.get_widget_value(count), Inherit)
        state.fields.count.write(None)
        qapp.processEvents()
        assert count.get_value() is None
        assert state.to_object().count is None
        state.fields.text.write(Unset())
        qapp.processEvents()
        assert isinstance(text.get_value(), Unset)
        state.fields.text.write(None)
        qapp.processEvents()
        assert text.get_value() is None


def test_native_input_and_reset_publish_one_canonical_change(qapp):
    with shown_form(qapp) as (state, manager):
        hooks, published = [], []
        manager.before_mutation = lambda: hooks.append('mutation')
        manager.parameter_changed.connect(lambda name, value: published.append((name, value)))
        with pytest.raises(FieldAccessError):
            manager.update_parameter('not_a_declaration', 'rejected')
        with pytest.raises(FieldAccessError):
            manager.reset_parameter('not_a_declaration')
        assert hooks == published == []
        loop, deadline = QEventLoop(), QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        release = state.fields.text.subscribe(lambda _fields: loop.quit() if state.fields.text.raw == 'typed' else None)
        try:
            text = manager.widgets['text']
            text.setFocus()
            QTest.keyClicks(text, 'typed')
            if state.fields.text.raw != 'typed':
                deadline.start(1000)
                loop.exec()
            assert state.fields.text.raw == 'typed'
        finally:
            deadline.stop()
            release()
        assert len(hooks) == len(published) == 1
        assert published[0] == ('text', 'typed')
        QTest.mouseClick(manager.reset_buttons['text'], Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert len(hooks) == len(published) == 2
        assert published[-1][0] == 'text' and isinstance(published[-1][1], Inherit)
        assert isinstance(text.get_value(), Inherit)
        assert state.fields.text.value == 'global text'


def test_enabled_paint_uses_backend_values_for_open_and_nested_forms(qapp):
    with shown_form(qapp) as (state, manager):
        text = manager.widgets['text']
        nested = manager.nested_managers['nested']
        nested_text = nested.widgets['text']
        # A stale painted checkbox is not a second enable-state authority.
        with SignalService.block_signals(manager.widgets['enabled']):
            manager.widgets['enabled'].setChecked(False)
        manager._enabled_field_styling_service.refresh_enabled_styling(manager)
        assert state.fields.enabled.value is True
        assert text.property('enabled_field_dimmed') is not True
        assert nested_text.property('enabled_field_dimmed') is not True
        state.fields.enabled.write(False)
        qapp.processEvents()
        assert text.property('enabled_field_dimmed') is True
        assert nested_text.property('enabled_field_dimmed') is True
        assert text.isEnabled() and nested_text.isEnabled()
        state.fields.enabled.write(True)
        qapp.processEvents()
        assert text.property('enabled_field_dimmed') is False
        assert nested_text.property('enabled_field_dimmed') is False
        state.fields.enabled.write(None)
        qapp.processEvents()
        assert manager.widgets['enabled'].get_value() is None
        assert state.fields.enabled.value is None
        assert text.property('enabled_field_dimmed') is True


def test_signal_scope_restores_each_widgets_original_block_state(qapp):
    text = QLineEdit()
    changes = []
    text.textChanged.connect(changes.append)
    try:
        with SignalService.block_signals(text):
            with SignalService.block_signals(text):
                text.setText('inner')
            assert text.signalsBlocked()
            text.setText('outer')
        assert not text.signalsBlocked() and changes == []
        text.setText('native')
        assert changes == ['native']
        text.blockSignals(True)
        with SignalService.block_signals(text):
            text.setText('still blocked')
        assert text.signalsBlocked() and changes == ['native']
    finally:
        text.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
