Server Scanning and Polling
===========================

Modules
-------

- ``pyqt_reactive.services.zmq_server_scan_service``
- ``pyqt_reactive.services.interval_snapshot_poller``
- ``pyqt_reactive.services.zmq_server_info``

ZMQServerScanService
--------------------

``ZMQServerScanService`` handles transport-level scanning:

- parallel per-port ping with bounded thread pool
- timeout-bounded REQ/REP ping through ``request_control_ping``
- preservation of the canonical ``PongResponse`` type

This keeps socket/network concerns outside widgets and raw dictionaries at the
wire boundary.

IntervalSnapshotPoller
----------------------

``IntervalSnapshotPoller`` is a generic background polling primitive:

- at-most-one inflight poll
- generation invalidation on reset
- snapshot cloning policy for isolation
- callback policy hooks for changed snapshot and poll errors

The policy boundary is formalized by ``IntervalSnapshotPollerPolicyABC``.

Typed Server Views
------------------

``BaseServerInfo.from_response`` selects a nominal view from the protocol-level
``ServerRole`` declared by the PONG type:

- ``ExecutionServerInfo``
- ``ViewerServerInfo``
- ``GenericServerInfo``

Execution views reuse ``WorkerState``, ``RunningExecutionInfo``, and
``QueuedExecutionInfo`` from zmqruntime. They do not retain or reconstruct raw
payload mappings.

Design Outcome
--------------

Widget code consumes typed snapshots through scanning, Qt item storage, polling,
and rendering. The declared classes are the schema; no parallel key table or
parser strategy is maintained.

See Also
--------

- :doc:`zmq_server_browser_widget`
- :doc:`service-layer-architecture`
