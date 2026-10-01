Safe window snapshots
=====================

``WindowSnapshotCaptureScope`` is the authority for screenshot scope and
capture behaviour. Each member renders pixels from an explicit Qt owner:

``WIDGET``
  Renders the requested ``QWidget``.

``WINDOW``
  Renders the requested widget's owning Qt window.

Both scopes use Qt rendering and therefore remain bounded to application-owned
pixels even when another desktop window overlaps the target. Native screen or
window-system grabs are intentionally absent because their platform-dependent
composition can sample unrelated desktop content.

``QtWindowSnapshotService`` persists the rendered pixmap as PNG and returns its
path, URI, dimensions, byte size, and SHA-256 digest. Product integrations own
window discovery, authorisation, and transport DTOs; they pass the resolved
``QWidget`` and a ``WindowSnapshotCaptureSpec`` into this generic service.

The scope and capture-spec declarations are safe to import in headless process
boundaries. PyQt types are used for static typing and capture execution without
eagerly importing PyQt while the declaration module is loaded.

Render-complete frames
----------------------

``WindowSnapshotFrameCondition.RENDER_COMPLETE`` requires a native renderer
completion receipt. Pass a ``WindowSnapshotRenderOwner`` on
``QtWindowSnapshotRequest`` and use ``QtWindowSnapshotService.request_capture``.
The shared observation ancestor arms the renderer signal before requesting a
frame, captures on completion, and owns the bounded deadline and cleanup.
Timeout and renderer destruction fail without persisting an image. Calling
``capture`` directly cannot silently treat an observed condition as immediate.

``OpenGLWidgetSnapshotRenderOwner`` supplies Qt's ``frameSwapped`` signal and
``update`` request from the existing ``QOpenGLWidget``. It does not paint, run
another event loop, inspect image content or estimate a settling duration.
Other native renderers declare only widget, completion-signal and frame-request
hooks. The same ancestor handles flash observations through their existing
flash painter; no condition switches belong in product consumers.

The receipt reports the target window, renderer identity and observed monotonic
completion time. It proves a requested native frame was completed, not that
future queued streaming work is settled or that scientific results are valid.
Products retain ownership of pending-work settlement and native integration.

Receiving Qt binding
--------------------

``QtWindowSnapshotService.qt_core`` supplies the owning integration's QtCore
module to the same observation timer and atomic PNG writer. Reactive forms
retain their original PyQt6 binding. A receiving Napari integration overrides
only this hook with its already-selected QtPy module; QtPy, not the capture
consumer, owns selection among its supported library bindings. There is no
widget-type dispatch, binding roster, environment override or canvas unwrap.

Vispy's ``Canvas.native`` is a real ``CanvasBackendDesktop`` whose MRO includes
the selected Qt ``QOpenGLWidget`` and ``QObject``. A PyQt5 widget cannot parent a
PyQt6 timer, and its pixmap cannot save to a PyQt6 device. Binding authority
therefore covers both operations, not only the first failing constructor.
The real hidden Vispy fixture tests timer parenting, typed no-frame failure,
late-signal cleanup and QLabel PNG persistence under QtPy/PyQt5 and PyQt6.
It deliberately draws no OpenGL frame; GL composition and installed viewer
acceptance remain separate obligations. A new integration declares only its
binding hook and inherits the unchanged capture/observation implementation.

Enclosing operation deadline
----------------------------

``QtWindowSnapshotRequest.operation_deadline`` accepts the original ZMQRuntime
``OperationDeadline``. It is armed by the operation owner before transport;
queue time is already consumed when the existing Qt observation timer starts.
``WindowSnapshotCaptureSpec.observation_phase_budget`` declares equal
observation and capture/reply phase allocation from the remaining budget.
This is a maximum budget, never an estimate of render latency or a settling
delay. Explicit observation bounds remain upper bounds and may be capped by
the enclosing operation. The timer remains on the existing observation owner.

Receipts retain the effective observation budget and original deadline.
Expired queued work fails with its typed receipt without requesting a frame.
Capture and PNG persistence recheck the same deadline. The original persistence
owner uses Qt's atomic ``QSaveFile``; a deadline crossed during commit or digest
removes only this operation's newly created artifact and fails once.

Monotonic deadlines require the same clock domain, as in the managed local
viewer processes tested here. These source checks do not qualify cross-host
deadline transfer or prove installed OpenGL composition.
