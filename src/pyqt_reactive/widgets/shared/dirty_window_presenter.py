"""Dirty-state presentation for ObjectState-backed form windows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from PyQt6.QtWidgets import QDialog, QLabel, QPushButton

if TYPE_CHECKING:
    from objectstate import ObjectState


@dataclass(frozen=True, slots=True)
class DirtyWindowPresentation:
    """Presentation state for a form window's dirty/signature-diff markers."""

    window_title: str
    header_text: str
    save_label: str
    is_dirty: bool
    has_signature_diff: bool
    mark_save_label_dirty: bool = True


@dataclass(slots=True)
class DirtyWindowStateTracker:
    """Track ObjectState dirty status for managed form windows."""

    state_provider: Callable[[], "ObjectState | None"]
    change_emitter: Callable[[bool], None]
    has_changes: bool = False

    @property
    def is_dirty(self) -> bool:
        state = self.state_provider()
        if state is None:
            return False
        return bool(state.is_raw_dirty)

    @property
    def has_signature_diff(self) -> bool:
        state = self.state_provider()
        if state is None:
            return False
        return bool(state.signature_diff_fields)

    def detect_changes(self) -> bool:
        has_changes = self.is_dirty
        if has_changes != self.has_changes:
            self.has_changes = has_changes
            self.change_emitter(has_changes)
        return has_changes


class DirtyWindowPresenter:
    """Apply dirty/signature-diff state to common form-window affordances."""

    def apply(
        self,
        *,
        window: QDialog,
        header_label: QLabel,
        save_button: QPushButton,
        presentation: DirtyWindowPresentation,
    ) -> None:
        dirty_prefix = ""
        if presentation.is_dirty:
            dirty_prefix = "* "
        window.setWindowTitle(f"{dirty_prefix}{presentation.window_title}")
        header_label.setText(f"{dirty_prefix}{presentation.header_text}")

        font = header_label.font()
        font.setUnderline(presentation.has_signature_diff)
        header_label.setFont(font)

        save_button.setEnabled(presentation.is_dirty)
        save_prefix = ""
        if presentation.mark_save_label_dirty and presentation.is_dirty:
            save_prefix = dirty_prefix
        save_button.setText(f"{save_prefix}{presentation.save_label}")
