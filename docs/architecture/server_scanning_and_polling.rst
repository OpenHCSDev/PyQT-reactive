Server Scanning and Polling
===========================

Modules
-------

- ``pyqt_reactive.services.zmq_server_scan_service``
- ``pyqt_reactive.services.interval_snapshot_poller``
- ``pyqt_reactive.services.zmq_server_info_parser``

ZMQServerScanService
--------------------

``ZMQServerScanService`` handles transport-level scanning:

- parallel per-port ping with bounded thread pool
- typed transport URL construction via ``zmqruntime.transport``
- timeout-bounded REQ/REP ping round-trips

This keeps socket/network concerns outside widgets.

IntervalSnapshotPoller
----------------------

``IntervalSnapshotPoller`` is a generic background polling primitive:

- at-most-one inflight poll
- generation invalidation on reset
- snapshot cloning policy for isolation
- callback policy hooks for changed snapshot and poll errors

The policy boundary is formalized by ``IntervalSnapshotPollerPolicyABC``.

Typed Ping Parsing
------------------

``DefaultServerInfoParser`` converts raw ping payloads into nominal types:

- ``ExecutionServerInfo``
- ``ViewerServerInfo``
- ``GenericServerInfo``

Execution payloads include typed compile status and running/queued execution
entries, enabling type-dispatched rendering in browser adapters.

Design Outcome
--------------

Widget code consumes typed parsed snapshots and no longer owns low-level socket
and parsing branches directly.

See Also
--------

- :doc:`zmq_server_browser_widget`
- :doc:`service-layer-architecture`
