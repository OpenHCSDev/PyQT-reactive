"""Tree state projection contracts."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from pyqt_reactive.widgets.shared import TreeNodeIdentity, TreeStateAdapter


def _identified_item(node_type: str, node_id: str) -> QTreeWidgetItem:
    item = QTreeWidgetItem([node_id])
    item.setData(
        0,
        Qt.ItemDataRole.UserRole,
        TreeNodeIdentity(node_type=node_type, node_id=node_id),
    )
    return item


def test_subtree_expansion_restores_known_items_and_defaults_new_items(qapp) -> None:
    tree = QTreeWidget()
    root = _identified_item("server", "server-1")
    known = _identified_item("plate", "plate-1")
    root.addChild(known)
    tree.addTopLevelItem(root)
    known.setExpanded(False)

    adapter = TreeStateAdapter.default()
    state = adapter.capture_subtree_expansion_state((known,))

    introduced = _identified_item("step", "step-1")
    known.addChild(introduced)
    adapter.restore_subtree_expansion_state(
        (known,),
        state,
        default_expanded=True,
    )

    assert not known.isExpanded()
    assert introduced.isExpanded()
