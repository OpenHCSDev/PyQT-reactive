ZMQ Server Browser Widget
=========================

Module
------

``pyqt_reactive.widgets.shared.zmq_server_browser_widget``

Purpose
-------

``ZMQServerBrowserWidgetABC`` provides reusable UI infrastructure for browsing
and controlling ZMQ servers without embedding domain logic in the base class.

Core Types
----------

- ``KillOperationPlan``
- ``ZMQServerBrowserWidgetABC``

What the Base Class Owns
------------------------

- refresh timer lifecycle
- background scan dispatch via ``ZMQServerScanService``
- generic tree rebuild with preserved expansion/selection state
- shared button panel actions (refresh, quit, force kill)
- kill operation threading + completion signaling
- server cache cleanup

Domain Hooks (Required Overrides)
---------------------------------

Subclasses provide domain-specific behavior by overriding abstract hooks:

- ``_populate_tree(parsed_servers)``
- ``_kill_ports_with_plan(...)``
- ``_periodic_domain_cleanup()``
- ``_on_browser_shown()``
- ``_on_browser_hidden()``
- ``_on_browser_cleanup()``

Related Infrastructure
----------------------

- ``pyqt_reactive.widgets.shared.manager_ui_scaffold``
  for standard manager header/layout assembly
- ``pyqt_reactive.widgets.shared.tree_rebuild_coordinator``
  for state-preserving rebuilds
- ``pyqt_reactive.services.zmq_server_scan_service``
  for typed parallel ping scans

Design Outcome
--------------

The base class gives one reusable browser shell while keeping server semantics,
tree rendering, and kill policy fully pluggable in downstream applications.

See Also
--------

- :doc:`tree_state_sync_system`
- :doc:`server_scanning_and_polling`
