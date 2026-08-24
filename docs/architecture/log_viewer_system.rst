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
* ``LogFileDetector`` watches for file changes and classifies them through the
  same host-owned provider as the window.
* ``LogViewerWindow`` composes selection, search, filtering, loading, tailing,
  and process tracking.

The earlier subprocess/JSONL clients and ``LogViewerWidget`` API are not part of
the current implementation.  Consumers should construct ``LogViewerWindow``.

Host-owned discovery
--------------------

Log discovery is an application boundary.  A host implements
``LogDiscoveryProviderABC`` and registers it before creating the window.  It
may also register a ``ServerScanProviderABC`` when server-log discovery is
available.

.. code-block:: python

   from pyqt_reactive.protocols.log_providers import (
       LogDiscoveryProviderABC,
       ServerScanProviderABC,
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

``LogDiscoveryProviderABC`` supplies ``get_current_log_path()`` and
``discover_logs(...)``.  ``ServerScanProviderABC`` supplies
``scan_for_server_logs()``.  The host also owns the ``file_manager`` and
``service_adapter`` dependencies passed to the window.  Construction fails
loudly if no log discovery provider has been registered.

The viewer refreshes server discovery while it is visible. Refresh requests are
coalesced so a slow provider never creates overlapping background scans.

Ownership boundary
------------------

pyqt-reactive owns log presentation and the generic nominal provider contracts.  The
host owns concrete paths, log naming, service discovery, and any domain-specific
status.  Add new discovery behavior by subclassing the relevant ABC at the host
boundary rather than teaching the viewer concrete application names.
