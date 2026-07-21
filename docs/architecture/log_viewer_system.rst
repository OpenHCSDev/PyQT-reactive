Log viewer system
=================

``pyqt_reactive.widgets.log_viewer`` provides a Qt log browser with asynchronous
file loading, live tailing, search, highlighting, log discovery, and process
status display.  It does not own an application's log locations or server
discovery policy.

Components
----------

The implementation is split into small Qt components:

* ``LogListModel``, ``LogItemDelegate``, and ``LogListView`` store and render
  highlighted lines.
* ``LogFileLoader`` and ``LogTailer`` are ``QThread`` workers for initial reads
  and appended data.
* ``LogHighlighter`` applies syntax highlighting in the viewer.
* ``LogFileDetector`` watches for file changes.
* ``LogViewerWindow`` composes selection, search, filtering, loading, tailing,
  and process tracking.

The earlier subprocess/JSONL clients and ``LogViewerWidget`` API are not part of
the current implementation.  Consumers should construct ``LogViewerWindow``.

Host-owned discovery
--------------------

Log discovery is an application boundary.  A host implements
``LogDiscoveryProvider`` and registers it before creating the window.  It may
also register a ``ServerScanProvider`` when server-log discovery is available.

.. code-block:: python

   from pyqt_reactive.protocols.log_providers import (
       register_log_discovery_provider,
       register_server_scan_provider,
   )
   from pyqt_reactive.widgets.log_viewer import LogViewerWindow

   register_log_discovery_provider(log_provider)
   register_server_scan_provider(server_provider)  # Optional.

   viewer = LogViewerWindow(
       file_manager=file_manager,
       service_adapter=service_adapter,
   )
   viewer.show()

``LogDiscoveryProvider`` supplies ``get_current_log_path()`` and
``discover_logs(...)``.  ``ServerScanProvider`` supplies
``scan_for_server_logs()``.  The host also owns the ``file_manager`` and
``service_adapter`` dependencies passed to the window.  Construction fails
loudly if no log discovery provider has been registered.

Ownership boundary
------------------

pyqt-reactive owns log presentation and the generic provider protocols.  The
host owns concrete paths, log naming, service discovery, and any domain-specific
status.  Add new discovery behavior by implementing the protocol at the host
boundary rather than teaching the viewer concrete application names.
