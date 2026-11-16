"""Tests for widget protocols."""

from abc import abstractmethod

import pytest
from formbridge.forms.declared_fields import DeclaredViews
from PySide6.QtWidgets import QWidget

from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta


def test_line_edit_adapter(qapp):
    """Test LineEditAdapter implements protocols."""
    from pyqt_reactive.protocols import LineEditAdapter, ValueGettable, ValueSettable
    
    adapter = LineEditAdapter()
    assert isinstance(adapter, ValueGettable)
    assert isinstance(adapter, ValueSettable)
    
    # Test value roundtrip
    adapter.set_value("test")
    assert adapter.get_value() == "test"


class _Hooks:
    """A plain mixin declaring one hook, as a contract an application declares."""

    @abstractmethod
    def hook(self) -> int: ...


class _Shown(DeclaredViews, QWidget, metaclass=PyQtWidgetMeta, shows=(int,)):
    pass


class _Open(_Hooks, QWidget, metaclass=PyQtWidgetMeta):
    pass


class _Closed(_Hooks, QWidget, metaclass=PyQtWidgetMeta):
    def hook(self) -> int:
        return 1


def test_qt_metaclass_delivers_class_keywords_and_refuses_open_hooks(qapp):
    assert _Shown.shows == (int,)
    with pytest.raises(TypeError, match="leaves hook abstract"):
        _Open()
    assert _Closed().hook() == 1
