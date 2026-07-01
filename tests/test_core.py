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


def test_managed_window_cleanup_unregisters_form_managers_once(qapp):
    """Managed window teardown disconnects form ObjectState listeners."""
    from pyqt_reactive.widgets.shared.base_form_dialog import BaseManagedWindow

    class FormManager:
        def __init__(self) -> None:
            self.unregister_count = 0

        def unregister_from_cross_window_updates(self) -> None:
            self.unregister_count += 1

    class ManagedWindow(BaseManagedWindow):
        def __init__(self, form_manager: FormManager) -> None:
            self._form_manager = form_manager
            super().__init__()

        def form_managers(self):
            return (self._form_manager,)

    form_manager = FormManager()
    window = ManagedWindow(form_manager)

    window._cleanup_managed_listeners()
    window._cleanup_managed_listeners()

    assert form_manager.unregister_count == 1
