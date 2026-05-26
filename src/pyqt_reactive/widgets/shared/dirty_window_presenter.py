"""Dirty-state presentation for ObjectState-backed form windows."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtWidgets import QDialog, QLabel, QPushButton


@dataclass(frozen=True, slots=True)
class DirtyWindowPresentation:
    """Presentation state for a form window's dirty/signature-diff markers."""

    window_title: str
    header_text: str
    save_label: str
    is_dirty: bool
    has_signature_diff: bool
    mark_save_label_dirty: bool = True


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
        dirty_prefix = "* " if presentation.is_dirty else ""
        window.setWindowTitle(f"{dirty_prefix}{presentation.window_title}")
        header_label.setText(f"{dirty_prefix}{presentation.header_text}")

        font = header_label.font()
        font.setUnderline(presentation.has_signature_diff)
        header_label.setFont(font)

        save_button.setEnabled(presentation.is_dirty)
        save_prefix = (
            dirty_prefix
            if presentation.mark_save_label_dirty and presentation.is_dirty
            else ""
        )
        save_button.setText(f"{save_prefix}{presentation.save_label}")
