"""
Shared reorderable QListWidget for drag-and-drop reordering.

Single source of truth for reorderable list widgets across PipelineEditor,
PlateManager, and other widgets.
"""

from PySide6.QtWidgets import QListWidget
from PySide6.QtCore import Signal, Qt


class ReorderableListWidget(QListWidget):
    """Custom QListWidget that properly handles drag and drop reordering.

    Emits a signal when items are moved so the parent can update the data model.
    This is a shared implementation used by both PipelineEditor and PlateManager.
    """

    items_reordered = Signal(int, int)  # from_index, to_index

    def __init__(self, parent=None):
        """Initialize reorderable list widget.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        # Wrapped rows may be taller than the viewport; every line must remain reachable.
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)

        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)

    def setWordWrap(self, enabled: bool) -> None:  # noqa: N802 - Qt virtual method
        """Reflow rows immediately and restore horizontal scrolling when disabled."""
        super().setWordWrap(enabled)
        # Individual rows may override this default; their size hints own overflow.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        if enabled:
            self.horizontalScrollBar().setValue(0)
        self.doItemsLayout()
        self.viewport().update()

    def dropEvent(self, event):
        """Handle drop event and emit signal with indices."""
        # Get the source index before the drop
        source_items = self.selectedItems()
        if not source_items:
            super().dropEvent(event)
            return

        source_index = self.row(source_items[0])

        # Perform the drop
        super().dropEvent(event)

        # Get the target index after the drop
        target_index = self.row(source_items[0])

        # Only emit signal if position actually changed
        if source_index != target_index:
            self.items_reordered.emit(source_index, target_index)
