"""Flash cleanup follows Qt destruction even when Python widget cycles are collected."""

import gc
from weakref import ref

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QDialog, QScrollArea, QTreeWidget, QTreeWidgetItem, QWidget

from pyqt_reactive.animation.flash_mixin import (
    VisualUpdateMixin,
    WindowFlashOverlay,
    _GlobalFlashCoordinator,
)


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



def _pending_widgets():
    return [
        registration.widget
        for registration in _GlobalFlashCoordinator.get()._pending_registrations
    ]


def test_pending_registration_ends_with_every_widget_it_closes_over(qapp):
    """A registration waiting for a flash window is dropped when Qt destroys
    any widget it closes over, so it never calls into a freed widget.

    The scroll area's viewport is created by Qt, not Python: its wrapper can
    outlive the native widget without sip marking it deleted.
    """

    host = QWidget()  # not a QMainWindow/QDialog: registrations must wait
    owner = FlashOwner(host)
    area = QScrollArea(host)
    viewport = area.viewport()
    leaf_host = QWidget(host)
    leaf = QWidget(leaf_host)
    owner.register_flash_widget_rect("viewport", viewport)
    owner.register_flash_leaf("leaf", host, leaf)

    assert _pending_widgets().count(viewport) == 1
    assert _pending_widgets().count(host) == 1

    area.deleteLater()
    leaf_host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert viewport not in _pending_widgets()
    assert host not in _pending_widgets()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
