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
