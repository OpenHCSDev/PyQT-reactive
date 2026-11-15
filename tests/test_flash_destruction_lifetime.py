"""Flash cleanup follows Qt destruction even when Python widget cycles are collected."""

import gc
from weakref import ref

from PyQt6 import sip
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QDialog, QTreeWidget, QTreeWidgetItem, QWidget

from pyqt_reactive.animation.flash_mixin import VisualUpdateMixin, WindowFlashOverlay


class FlashOwner(QWidget, VisualUpdateMixin):
    def __init__(self, parent):
        super().__init__(parent)
        self._init_visual_update_mixin()


def test_tree_cleanup_survives_cycle_collection_before_deferred_destruction(qapp):
    def queue_window_destruction():
        window = QDialog()
        owner = FlashOwner(window)
        tree = QTreeWidget(window)
        tree.addTopLevelItem(QTreeWidgetItem(["Parameters"]))
        owner.register_flash_tree_item(
            "parameters", tree, lambda: tree.indexFromItem(tree.topLevelItem(0))
        )
        window.show()
        qapp.processEvents()
        WindowFlashOverlay.cleanup_window(window)
        window.deleteLater()
        return ref(window)

    for _ in range(10):
        window_ref = queue_window_destruction()
        gc.collect()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        window = window_ref()
        assert window is None or sip.isdeleted(window)
