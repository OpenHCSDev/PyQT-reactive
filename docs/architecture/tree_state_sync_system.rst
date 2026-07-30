Tree State Sync System
======================

Modules
-------

- ``pyqt_reactive.widgets.shared.tree_state_adapter``
- ``pyqt_reactive.widgets.shared.tree_rebuild_coordinator``
- ``pyqt_reactive.widgets.shared.tree_sync_adapter``

Problem
-------

Frequent tree refreshes can destroy user context (collapsed nodes re-open,
selection disappears, stale children remain).

Solution
--------

pyqt-reactive splits tree concerns into orthogonal adapters:

- ``TreeStateAdapter``: capture/restore expansion and selected-item state
- ``TreeRebuildCoordinator``: clear + rebuild + restore in one safe sequence
- ``TreeSyncAdapter``: recursive typed node synchronization and child pruning

Stable Item Identity
--------------------

``TreeItemKeyBuilderABC`` provides stable keys per item. The default
``TypedPayloadTreeItemKeyBuilder`` asks nominal payloads implementing
``TreeItemKeyProvider`` for their stable key and falls back to visible text
when no typed payload is present.

Typed Node Model
----------------

``TreeNode`` is a pure data representation for tree rows. ``TreeSyncAdapter``
stores the corresponding immutable ``TreeNodeIdentity`` in each Qt item:

- ``node_id``
- ``node_type``
- ``label``
- ``status``
- ``info``
- ``children``

This keeps synchronization deterministic and testable.

Usage Pattern
-------------

1. Build typed ``TreeNode`` structures from domain state.
2. Use ``TreeSyncAdapter.sync_children`` to mutate Qt items.
3. Wrap full refresh in ``TreeRebuildCoordinator.rebuild`` to preserve user state.

See Also
--------

- :doc:`zmq_server_browser_widget`
- :doc:`tree_aggregation_strategy`
