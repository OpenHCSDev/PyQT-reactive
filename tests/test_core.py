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


def test_managed_window_show_replays_flash_registrations(qapp, monkeypatch):
    """Shown form windows re-anchor flash registrations to the live top-level window."""
    from pyqt_reactive.animation import WindowFlashOverlay
    from pyqt_reactive.services.window_manager import WindowManager
    from pyqt_reactive.widgets.shared.base_form_dialog import BaseManagedWindow

    overlay_windows = []

    def fake_get_for_window(cls, widget):
        overlay_windows.append(widget)
        return None

    monkeypatch.setattr(
        WindowFlashOverlay,
        "get_for_window",
        classmethod(fake_get_for_window),
    )

    class FormTree:
        def __init__(self, root):
            self._root = root

        def root(self):
            return self._root

    class FormManager:
        def __init__(self) -> None:
            self.form_tree = FormTree(self)
            self.reregister_count = 0
            self.unregister_count = 0

        def reregister_flash_elements(self) -> None:
            self.reregister_count += 1

        def unregister_from_cross_window_updates(self) -> None:
            self.unregister_count += 1

    class ManagedWindow(BaseManagedWindow):
        scope_id = "flash_scope"

        def __init__(self, form_manager: FormManager) -> None:
            self._form_manager = form_manager
            super().__init__()

        def form_managers(self):
            return (self._form_manager,)

    form_manager = FormManager()
    window = ManagedWindow(form_manager)

    try:
        window.show()
        qapp.processEvents()

        assert window in overlay_windows
        assert form_manager.reregister_count == 1
    finally:
        window.close()
        qapp.processEvents()
        WindowManager.unregister("flash_scope")


def test_live_context_refresh_replays_root_flash_registrations():
    """Live placeholder refresh keeps existing form flash registrations current."""
    from pyqt_reactive.services.parameter_ops_service import ParameterOpsService

    class FormManager:
        _parent_manager = None

        def __init__(self) -> None:
            self.field_id = "root"
            self.placeholder_refresh_count = 0
            self.reregister_count = 0

        def _apply_to_nested_managers(self, callback):
            del callback

        def reregister_flash_elements(self) -> None:
            self.reregister_count += 1

    manager = FormManager()
    service = ParameterOpsService()

    def refresh_all_placeholders(target):
        target.placeholder_refresh_count += 1

    service.refresh_all_placeholders = refresh_all_placeholders

    service.refresh_with_live_context(manager)

    assert manager.placeholder_refresh_count == 1
    assert manager.reregister_count == 1


def test_deferred_live_context_refresh_obeys_manager_qobject_lifetime(qapp):
    """Deferred form work is cancelled when Qt destroys its manager owner."""
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QWidget

    from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager
    from pyqt_reactive.services.parameter_ops_service import ParameterOpsService

    class FormManager(QWidget):
        field_id = "root"
        schedule_lifecycle_callback = (
            ParameterFormManager.schedule_lifecycle_callback
        )

    service = ParameterOpsService()
    refreshed = []
    service._deferred_refresh_with_live_context = refreshed.append

    live_manager = FormManager()
    service.refresh_with_live_context(live_manager, defer=True)
    qapp.processEvents()
    assert refreshed == [live_manager]

    live_manager.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    refreshed.clear()
    deleted_manager = FormManager()
    service.refresh_with_live_context(deleted_manager, defer=True)
    deleted_manager.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(deleted_manager)

    qapp.processEvents()
    assert refreshed == []


def test_window_flash_overlay_replaces_stale_cached_overlay(qapp, monkeypatch):
    """Overlay cache entries stay owned by the exact live top-level window."""
    from PyQt6.QtWidgets import QDialog
    import pyqt_reactive.animation.flash_mixin as flash_mixin
    from pyqt_reactive.animation.flash_mixin import WindowFlashOverlay

    class FlashConfig:
        use_opengl = False

    monkeypatch.setattr(flash_mixin, "get_flash_config", lambda: FlashConfig())

    old_window = QDialog()
    live_window = QDialog()
    old_overlay = WindowFlashOverlay(old_window)
    WindowFlashOverlay._overlays[id(live_window)] = old_overlay

    try:
        live_overlay = WindowFlashOverlay.get_for_window(live_window)

        assert live_overlay is not old_overlay
        assert live_overlay._window is live_window
        assert WindowFlashOverlay._overlays[id(live_window)] is live_overlay
    finally:
        WindowFlashOverlay.cleanup_window(old_window)
        WindowFlashOverlay.cleanup_window(live_window)
        qapp.processEvents()


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
