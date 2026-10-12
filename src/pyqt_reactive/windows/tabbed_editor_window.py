"""A save/cancel window that hosts a declared family of tabs over one edited object.

An application declares what is edited (an ``EditedObject``) and the tabs that
edit it (``EditorTab`` subclasses of the family the edited object names). The
window renders whatever the family declares: adding a tab is adding a class.
"""

from __future__ import annotations

import inspect
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar, TypeVar

from formbridge.forms.layout_constants import CURRENT_LAYOUT
from formbridge.services.window_code_document import WindowCodeDocumentDriver
from objectstate.object_state import ObjectState, ObjectStateRegistry
from PyQt6.QtCore import QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QShowEvent
from PyQt6.QtWidgets import QLabel, QMessageBox, QPushButton, QVBoxLayout

from pyqt_reactive.services.window_navigation import (
    CompositeWindowNavigationDriver,
    NullWindowNavigationDriver,
    RegisteredWindowNavigationRequest,
    WindowNavigationDriver,
)
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.shared.action_tabbed_window_body import (
    ActionTabbedWindowBody,
    ActionTabMaterialization,
    ActionTabSpec,
)
from pyqt_reactive.widgets.shared.base_form_dialog import (
    BaseFormDialog,
    ManagedWindowActionCapabilities,
)
from pyqt_reactive.widgets.shared.dirty_window_presenter import DirtyWindowPresentation
from pyqt_reactive.widgets.shared.form_window_action_header import (
    FormWindowActionHeader,
    HeaderAction,
    HeaderActionGroup,
)

if TYPE_CHECKING:
    from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager

logger = logging.getLogger(__name__)

TabT = TypeVar("TabT", bound="EditorTab")


class SaveRefused(Exception):
    """The edited object cannot be saved as it stands; the message is shown to the user."""


class EditorTab(ABC):
    """One tab of a ``TabbedEditorWindow``.

    A tab belongs to a window by inheriting from the tab family its edited
    object names. Everything the window needs from a tab is a method here, so
    the window never asks which tab it is talking to.
    """

    label: ClassVar[str]

    def __init__(self, window: TabbedEditorWindow) -> None:
        self.window = window

    @classmethod
    def declared_tabs(cls) -> tuple[type[EditorTab], ...]:
        """Every concrete tab of this family, in declaration order."""
        tabs: list[type[EditorTab]] = []
        for tab_type in cls.__subclasses__():
            if not inspect.isabstract(tab_type):
                tabs.append(tab_type)
            tabs.extend(tab_type.declared_tabs())
        return tuple(tabs)

    @abstractmethod
    def build(self) -> ActionTabMaterialization:
        """Build this tab's content and its action widgets."""

    def form_managers(self) -> tuple[ParameterFormManager, ...]:
        """Root form managers whose edits mark the window dirty."""
        return ()

    def navigation_driver(self) -> WindowNavigationDriver:
        """Navigation to the field paths this tab shows."""
        return NullWindowNavigationDriver()

    def code_document_driver(self) -> WindowCodeDocumentDriver | None:
        """The code document this tab edits, if it edits one."""
        return None

    def apply_scope_accent(self, accent_color: QColor) -> None:
        """Colour this tab's widgets with the window's scope accent."""
        del accent_color

    def write_pending_edits(self) -> None:
        """Write edits this tab holds outside the ObjectState into it, before a save."""

    def refresh_from_state(self) -> None:
        """Redraw after the ObjectState changed outside this tab."""

    def release(self) -> None:
        """Release subscriptions this tab owns."""

    def select(self) -> None:
        """Show this tab."""
        self.window.tab_body.set_current_index(self.window.tabs.index(self))


class EditedObject(ABC):
    """What a ``TabbedEditorWindow`` edits: its identity, its tabs and how it is saved."""

    tab_family: ClassVar[type[EditorTab]]
    #: Position among sibling objects; picks the scope border pattern.
    list_position: int | None = None

    @property
    @abstractmethod
    def scope_id(self) -> str:
        """ObjectState scope of the edited object; also the window's identity."""

    @property
    @abstractmethod
    def state(self) -> ObjectState:
        """The ObjectState that holds the edits and is restored on cancel."""

    @abstractmethod
    def title(self) -> str:
        """Window and header title, without the dirty marker."""

    def save_label(self) -> str:
        return "Save"

    @abstractmethod
    def save(self) -> object:
        """Commit the edits and return what was saved. Raise ``SaveRefused`` if invalid."""

    def require_mutation_allowed(self) -> None:
        """Raise if the edited object may not be saved or discarded right now."""


class TabbedEditorNavigationDriver(CompositeWindowNavigationDriver):
    """Navigate through the tab that owns the target, showing that tab first.

    Each driver is kept with the tab that supplied it, so a navigation can be
    traced to the tab declaration that handled it.
    """

    def __init__(self, tabs: tuple[EditorTab, ...]) -> None:
        self.tab_drivers = tuple((tab, tab.navigation_driver()) for tab in tabs)
        super().__init__(tuple(driver for _tab, driver in self.tab_drivers))

    def owning_tabs(self, request: RegisteredWindowNavigationRequest) -> tuple[EditorTab, ...]:
        matching = self._matching_drivers(request)
        return tuple(tab for tab, driver in self.tab_drivers if driver in matching)

    def prepare(self, request: RegisteredWindowNavigationRequest) -> None:
        for tab in self.owning_tabs(request):
            tab.select()
        super().prepare(request)


class TabbedEditorWindow(BaseFormDialog):
    """Edit one object through the tabs its tab family declares."""

    saved = pyqtSignal(object)
    cancelled = pyqtSignal()

    default_size: ClassVar[QSize] = QSize(550, 600)

    def __init__(
        self,
        edited: EditedObject,
        *,
        color_scheme: ColorScheme | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.edited = edited
        self.color_scheme = color_scheme or ColorScheme()
        self.setModal(False)
        self.scope_id = edited.scope_id
        self._step_index = edited.list_position
        self._default_size_applied = False

        self.tabs: tuple[EditorTab, ...] = ()
        self._build_shell()
        self.init_scope_border()

        self.tabs = tuple(
            tab_type(self) for tab_type in type(edited).tab_family.declared_tabs()
        )
        for tab in self.tabs:
            built = tab.build()
            self.tab_body.add_tab(
                ActionTabSpec(label=tab.label, content=built.content, actions=built.actions)
            )
        self._navigation_driver = TabbedEditorNavigationDriver(self.tabs)
        self.apply_scope_accent_styling()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh_tabs_from_state)
        for form_manager in self.form_managers():
            form_manager.parameter_changed.connect(self._schedule_tab_refresh)
        edited.state.on_state_changed(self._on_state_fields_changed)
        edited.state.on_resolved_changed(self._on_state_fields_changed)

        self.detect_changes()
        self.apply_dirty_window_presentation()
        self.connect_change_detection()
        self._time_travel_subscription = ObjectStateRegistry.add_time_travel_complete_callback(
            self._on_time_travel_complete
        )
        self.destroyed.connect(self._time_travel_subscription.release)

    # -- shell ----------------------------------------------------------------

    def _build_shell(self) -> None:
        if self.size().isEmpty():
            self.resize(self.default_size)
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(5, 5, 5, 5)
        compact_style = self.color_scheme.styles.generate_config_button_styles()["compact"]

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton(self.edited.save_label())
        self.save_button.setEnabled(False)
        self.setup_save_button(self.save_button, self.save_managed_window)
        for button in (cancel_button, self.save_button):
            button.setFixedHeight(CURRENT_LAYOUT.button_height)
            button.setMinimumWidth(70)
            button.setStyleSheet(compact_style)

        header = FormWindowActionHeader(
            title_text="",
            title_color=self.color_scheme.to_hex(self.color_scheme.text_accent),
            action_groups=[
                HeaderActionGroup(
                    "group_save",
                    [HeaderAction("cancel", cancel_button), HeaderAction("save", self.save_button)],
                )
            ],
            stay_priority=["group_save"],
            right_aligned_group_ids=["group_save"],
            parent=self,
        )
        header.setStyleSheet(
            "QWidget {"
            f" background-color: {self.color_scheme.to_hex(self.color_scheme.panel_bg)};"
            " border-radius: 3px; }"
        )
        self.header_label: QLabel = header.header_label
        layout.addWidget(header)

        self.tab_body = ActionTabbedWindowBody(color_scheme=self.color_scheme, parent=self)
        layout.addWidget(self.tab_body, 1)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt virtual method name
        super().showEvent(event)
        if not self._default_size_applied:
            self.resize(self.default_size)
            self._default_size_applied = True

    def tab(self, tab_type: type[TabT]) -> TabT:
        """The window's tab of the given declared type."""
        matches = tuple(tab for tab in self.tabs if isinstance(tab, tab_type))
        if len(matches) != 1:
            raise LookupError(f"Expected one {tab_type.__name__} tab, found {len(matches)}.")
        return matches[0]

    # -- what BaseFormDialog asks ---------------------------------------------

    @property
    def state(self) -> ObjectState:
        return self.edited.state

    def form_managers(self) -> tuple[ParameterFormManager, ...]:
        return tuple(manager for tab in self.tabs for manager in tab.form_managers())

    def window_navigation_driver(self) -> WindowNavigationDriver:
        return self._navigation_driver

    def window_code_document_driver(self) -> WindowCodeDocumentDriver | None:
        current = self.tab_body.current_index()
        ordered = (*self.tabs[current : current + 1], *self.tabs)
        for tab in ordered:
            driver = tab.code_document_driver()
            if driver is not None:
                return driver
        return None

    def managed_window_action_capabilities(self) -> ManagedWindowActionCapabilities:
        return ManagedWindowActionCapabilities(
            save_and_close=True,
            save_without_close=True,
            discard_and_close=True,
        )

    def agent_save_managed_window(self, *, close_window: bool) -> None:
        self.save_managed_window(close_window=close_window)

    def require_managed_state_mutation_allowed(self) -> None:
        self.edited.require_mutation_allowed()

    def dirty_window_widgets(self) -> tuple[QLabel, QPushButton]:
        return self.header_label, self.save_button

    def dirty_window_presentation(self) -> DirtyWindowPresentation:
        title = self.edited.title()
        return DirtyWindowPresentation(
            window_title=title,
            header_text=title,
            save_label=self.edited.save_label(),
            is_dirty=self.dirty_state.is_dirty,
            has_signature_diff=self.dirty_state.has_signature_diff,
            mark_save_label_dirty=True,
        )

    # -- save / cancel --------------------------------------------------------

    def save_managed_window(self, *, close_window: bool = True) -> None:
        """Save the edited object; close afterwards unless told to stay open."""
        try:
            self.require_managed_state_mutation_allowed()
            for tab in self.tabs:
                tab.write_pending_edits()
            saved = self.edited.save()
            self.saved.emit(saved)
        except SaveRefused as refusal:
            QMessageBox.warning(self, "Validation Error", str(refusal))
            return
        except Exception as error:
            logger.exception("Failed to save %s", type(self.edited).__name__)
            QMessageBox.critical(self, "Save Error", f"Failed to save:\n{error}")
            return
        self.finish_managed_save(close_window=close_window)
        self.apply_dirty_window_presentation()

    def before_managed_reject(self) -> None:
        self.cancelled.emit()

    def after_managed_reject(self) -> None:
        ObjectStateRegistry.increment_token()

    def _cleanup_managed_resources(self) -> None:
        if not self._managed_resource_cleanup_done:
            self._time_travel_subscription.release()
            self.edited.state.off_state_changed(self._on_state_fields_changed)
            self.edited.state.off_resolved_changed(self._on_state_fields_changed)
            for tab in self.tabs:
                tab.release()
        super()._cleanup_managed_resources()

    # -- keeping tabs and title in step with the state ------------------------

    def tab_edited_state(self, editing_tab: EditorTab) -> None:
        """A tab wrote to the ObjectState: redraw the other tabs and the dirty markers."""
        for tab in self.tabs:
            if tab is not editing_tab:
                tab.refresh_from_state()
        self.detect_changes()

    def refresh_tabs_from_state(self) -> None:
        for tab in self.tabs:
            tab.refresh_from_state()
        self.detect_changes()
        self.apply_dirty_window_presentation()

    def _schedule_tab_refresh(self, *_parameter_change) -> None:
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(0)

    def _on_state_fields_changed(self, _fields: set) -> None:
        self.detect_changes()
        self.apply_dirty_window_presentation()

    def _on_time_travel_complete(self, _dirty_states, _triggering_scope) -> None:
        self._schedule_tab_refresh()

    # -- scope accent ---------------------------------------------------------

    def apply_scope_accent_styling(self) -> None:
        super().apply_scope_accent_styling()
        accent_color = self.get_scope_accent_color()
        if accent_color is None:
            raise RuntimeError(
                "Scope accent color is missing; call init_scope_border() after setting scope_id"
            )
        self.save_button.setStyleSheet(
            self.color_scheme.styles.generate_scope_accent_button_style(accent_color)
        )
        self.header_label.setStyleSheet(f"color: {accent_color.name()};")
        self.tab_body.apply_accent(accent_color)
        for tab in self.tabs:
            tab.apply_scope_accent(accent_color)

        from pyqt_reactive.animation import WindowFlashOverlay

        WindowFlashOverlay.get_for_window(self)
        self._flash_overlay_cleaned = False
