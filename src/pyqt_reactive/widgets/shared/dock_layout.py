"""Main-window dock panes that float, redock and persist their layout."""

from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import QByteArray, QSettings, QSize, Qt, QTimer
from PyQt6.QtWidgets import QDockWidget, QMainWindow, QStyle, QToolButton, QWidget

from pyqt_reactive.widgets.shared.manager_ui_scaffold import ManagerHeaderParts


@dataclass(slots=True, weakref_slot=True)
class DockFloatController:
    """Toggle one dock while preserving its complete pre-float workspace slot."""

    main_window: QMainWindow
    dock_widget: QDockWidget
    docked_content_height: int | None = None
    preferred_floating_size: QSize | None = None
    _docked_state: QByteArray | None = None
    _floating_size: QSize | None = field(init=False, repr=False)
    _content_minimum_height: int = field(init=False, repr=False)
    _content_maximum_height: int = field(init=False, repr=False)
    _dock_transition_timer: QTimer = field(init=False, repr=False)
    _top_level_sync_timer: QTimer = field(init=False, repr=False)
    _pending_top_level_state: bool | None = field(default=None, init=False, repr=False)
    _redock_pending: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        content = self.dock_widget.widget()
        if content is None:
            raise RuntimeError("Dock float controller requires a content widget")
        if self.preferred_floating_size is not None and (
            self.preferred_floating_size.width() <= 0 or self.preferred_floating_size.height() <= 0
        ):
            raise ValueError("Preferred floating size must be positive")
        self._floating_size = (
            QSize(self.preferred_floating_size)
            if self.preferred_floating_size is not None
            else None
        )
        self._content_minimum_height = content.minimumHeight()
        self._content_maximum_height = content.maximumHeight()
        self._dock_transition_timer = QTimer(self.main_window)
        self._dock_transition_timer.setSingleShot(True)
        self._dock_transition_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._dock_transition_timer.setInterval(1)
        self._dock_transition_timer.timeout.connect(self._restore_docked_workspace)
        self._top_level_sync_timer = QTimer(self.main_window)
        self._top_level_sync_timer.setSingleShot(True)
        self._top_level_sync_timer.setInterval(0)
        self._top_level_sync_timer.timeout.connect(self._apply_pending_top_level_state)
        self.sync_top_level(self.dock_widget.isFloating())

    def sync_top_level(self, is_floating: bool) -> None:
        """Apply embedded-only sizing while leaving floating panes resizable."""

        if self.docked_content_height is None:
            return
        content = self.dock_widget.widget()
        if content is None:
            return
        if is_floating:
            content.setMinimumHeight(self._content_minimum_height)
            content.setMaximumHeight(self._content_maximum_height)
            return
        if self._redock_pending:
            return
        content.setFixedHeight(self.docked_content_height)

    def set_docked_content_height(self, height: int) -> None:
        """Update the content owner's embedded height projection."""

        if height <= 0:
            raise ValueError("Docked content height must be positive")
        if height == self.docked_content_height:
            return
        self.docked_content_height = height
        self.sync_top_level(self.dock_widget.isFloating())

    def schedule_top_level_sync(self, is_floating: bool) -> None:
        """Apply dock constraints after Qt completes its native transition."""

        self._pending_top_level_state = is_floating
        self._top_level_sync_timer.start()

    def _apply_pending_top_level_state(self) -> None:
        is_floating = self._pending_top_level_state
        if is_floating is None:
            return
        self._pending_top_level_state = None
        self.sync_top_level(is_floating)

    def toggle(self) -> None:
        if not self.dock_widget.isFloating():
            self._docked_state = self.main_window.saveState()
            self.dock_widget.setFloating(True)
            self.dock_widget.show()
            if self._floating_size is not None:
                self.dock_widget.resize(self._floating_size)
            QTimer.singleShot(0, self._reveal_after_layout)
            return

        self._floating_size = self.dock_widget.size()
        self._redock_pending = True
        self.dock_widget.setFloating(False)
        if self._docked_state is None:
            self._redock_pending = False
            self.sync_top_level(False)
            self._reveal_after_layout()
            return

        # A resized floating QDockWidget completes its native dock transition
        # on the next event-loop turn. Restore the one authoritative workspace
        # snapshot after that transition so the first click recovers the prior
        # slot geometry instead of retaining the floating window dimensions.
        # Qt emits topLevelChanged(False) before its dock layout has consumed
        # a resized floating window. The first timed event-loop turn is the
        # earliest boundary at which restoreState can recover the saved slot.
        self._dock_transition_timer.start()

    def _restore_docked_workspace(self) -> None:
        # Reapply embedded-only constraints before asking Qt to consume the
        # saved layout. A resized floating pane otherwise contributes its
        # top-level width to restoreState on slower event loops, leaving a
        # fixed-height dock partially redocked at the floating geometry.
        self._redock_pending = False
        self.sync_top_level(False)
        if self._docked_state is not None:
            if not self.main_window.restoreState(self._docked_state):
                self.dock_widget.setFloating(False)
        QTimer.singleShot(0, self._reveal_after_layout)

    def _reveal_after_layout(self) -> None:
        self.dock_widget.show()
        self.dock_widget.raise_()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class DockPane:
    """One logical embedded pane and its native Qt geometry owner."""

    window_id: str
    title: str
    widget: QWidget
    dock_widget: QDockWidget
    float_controller: DockFloatController | None = None
    float_button: QToolButton | None = None

    @classmethod
    def create(
        cls,
        *,
        main_window: QMainWindow,
        window_id: str,
        title: str,
        widget: QWidget,
        manager_header: ManagerHeaderParts | None = None,
        docked_content_height: int | None = None,
        preferred_floating_size: QSize | None = None,
    ) -> DockPane:
        dock_widget = QDockWidget(title, main_window)
        dock_widget.setObjectName(window_id)
        dock_widget.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock_widget.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock_widget.toggleViewAction().setVisible(False)
        dock_widget.setWidget(widget)
        float_button = None
        float_controller = None
        if manager_header is not None:
            content_layout = widget.layout()
            if content_layout is None:
                raise RuntimeError(
                    f"Dock pane {window_id!r} has no content layout for its manager header"
                )
            content_layout.removeWidget(manager_header.header)
            manager_header.present_as_dock_title()
            float_button = cls._title_button(
                dock_widget=dock_widget,
                object_name=f"{window_id}_dock_float_button",
                tooltip="Float pane",
            )
            float_controller = DockFloatController(
                main_window=main_window,
                dock_widget=dock_widget,
                docked_content_height=docked_content_height,
                preferred_floating_size=preferred_floating_size,
            )

            def sync_float_button(is_floating: bool) -> None:
                standard_icon = (
                    QStyle.StandardPixmap.SP_TitleBarNormalButton
                    if is_floating
                    else QStyle.StandardPixmap.SP_TitleBarMaxButton
                )
                float_button.setIcon(dock_widget.style().standardIcon(standard_icon))
                float_button.setToolTip("Dock pane" if is_floating else "Float pane")

            float_button.clicked.connect(float_controller.toggle)
            dock_widget.topLevelChanged.connect(sync_float_button)
            dock_widget.topLevelChanged.connect(float_controller.schedule_top_level_sync)
            sync_float_button(dock_widget.isFloating())
            manager_header.title_layout.add_right_widget(float_button)
            dock_widget.setTitleBarWidget(manager_header.header)
        return cls(
            window_id=window_id,
            title=title,
            widget=widget,
            dock_widget=dock_widget,
            float_controller=float_controller,
            float_button=float_button,
        )

    @staticmethod
    def _title_button(
        *,
        dock_widget: QDockWidget,
        object_name: str,
        tooltip: str,
    ) -> QToolButton:
        button = QToolButton(dock_widget)
        button.setObjectName(object_name)
        button.setAutoRaise(True)
        button.setIconSize(QSize(12, 12))
        button.setFixedSize(18, 18)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button

    def set_docked_content_height(self, height: int) -> None:
        """Delegate a content-owned embedded height to the dock controller."""

        if self.float_controller is None:
            raise RuntimeError(f"Dock pane {self.window_id!r} has no float controller")
        self.float_controller.set_docked_content_height(height)

    def show(self) -> None:
        """Reveal and focus this pane without changing its dock geometry."""

        self.dock_widget.show()
        self.dock_widget.raise_()
        self.widget.setFocus(Qt.FocusReason.OtherFocusReason)


@dataclass(slots=True)
class DockPanes:
    """The permanent dock panes of one main window, by window id."""

    _panes: dict[str, DockPane] = field(default_factory=dict)

    def configure_host(self, main_window: QMainWindow) -> None:
        """Configure stable native docking without reentrant drag animation."""

        main_window.setDockNestingEnabled(True)
        main_window.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AllowTabbedDocks
        )

    def register(self, pane: DockPane) -> None:
        if pane.window_id in self._panes:
            raise ValueError(f"Duplicate dock pane id: {pane.window_id!r}")
        self._panes[pane.window_id] = pane

    def panes(self) -> tuple[DockPane, ...]:
        return tuple(self._panes.values())

    def require_pane(self, window_id: str) -> DockPane:
        try:
            return self._panes[window_id]
        except KeyError as exc:
            raise RuntimeError(f"Dock pane {window_id!r} has not been initialized") from exc

    def ensure_all_visible(self) -> None:
        """Keep every permanent workspace pane either docked or floating."""

        for pane in self.panes():
            pane.dock_widget.show()


@dataclass(slots=True)
class DockLayoutStore:
    """Persist the main window's opaque native dock geometry in ``QSettings``.

    A stored state that is not a byte array, or that Qt refuses, is discarded and
    the default layout is kept.
    """

    settings: QSettings
    state_key: str
    state_version: int

    @classmethod
    def for_application(cls, *, state_key: str, state_version: int) -> DockLayoutStore:
        """Store in the running application's ``QSettings`` (its organization and name)."""

        return cls(settings=QSettings(), state_key=state_key, state_version=state_version)

    def restore(self, main_window: QMainWindow) -> bool:
        stored_state = self.settings.value(self.state_key)
        if stored_state is None:
            return False

        default_state = main_window.saveState(self.state_version)
        if not isinstance(stored_state, QByteArray):
            self._discard_invalid_state()
            return False
        if main_window.restoreState(stored_state, self.state_version):
            return True

        main_window.restoreState(default_state, self.state_version)
        self._discard_invalid_state()
        return False

    def save(self, main_window: QMainWindow) -> None:
        self.settings.setValue(
            self.state_key,
            main_window.saveState(self.state_version),
        )
        self.settings.sync()

    def _discard_invalid_state(self) -> None:
        self.settings.remove(self.state_key)
        self.settings.sync()
