"""Tests for core utilities."""


def test_debounce_timer_basic(qapp):
    """Test DebounceTimer basic functionality."""
    from pyqt_reactive.core import DebounceTimer
    
    called = []
    def handler():
        called.append(1)
    
    timer = DebounceTimer(delay_ms=50, handler=handler)
    assert len(called) == 0
    
    # Basic test - timer exists
    assert timer is not None


def test_reorderable_list_widget(qapp):
    """Test ReorderableListWidget creation."""
    from pyqt_reactive.core import ReorderableListWidget
    
    widget = ReorderableListWidget()
    assert widget is not None


def test_managed_window_registers_declared_window_scope(qapp):
    """Managed windows may expose a UI window id distinct from model scope."""
    from pyqt_reactive.services.window_manager import WindowManager
    from pyqt_reactive.widgets.shared.base_form_dialog import BaseManagedWindow

    class WindowScopeManagedWindow(BaseManagedWindow):
        scope_id = "object_scope"

        def window_manager_scope_id(self) -> str:
            return "window_scope"

    window = WindowScopeManagedWindow()

    try:
        window.show()
        qapp.processEvents()

        assert WindowManager.get_window("window_scope") is window
        assert WindowManager.get_window("object_scope") is None
    finally:
        window.close()
        qapp.processEvents()
        WindowManager.unregister("window_scope")
        WindowManager.unregister("object_scope")
