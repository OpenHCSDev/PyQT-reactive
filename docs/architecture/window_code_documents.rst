Window code documents
=====================

``WindowCodeDocumentDriver`` is the generic code-mode capability for a managed
window. It separates window management and editor presentation from the
domain-specific meaning of rendered source.

Document boundary
-----------------

``WindowCodeDocument`` is an immutable value with ``title``, ``source``, and
``mime_type``. The default MIME type is Python, but the service boundary does
not interpret the source.

A driver implements three operations:

``read_document(clean=True)``
   Render the current window-owned state as a document. The meaning of
   ``clean`` is supplied by the concrete driver.

``validate_source(source)``
   Parse and validate source without mutating window or application state.

``apply_source(source)``
   Apply valid source through the same state transition used by interactive
   code mode.

``WindowCodeDocumentError`` reports that a managed window cannot service a
document request. Parse or domain validation errors may remain more specific.

Revision and history ownership
------------------------------

``current_revision_token()`` defaults to ``None``. A driver returns a token
when its document has a local revision authority distinct from ObjectState.
Window management can use that token to detect stale editor content without
understanding the document schema.

``records_object_state_snapshot_on_apply()`` defaults to ``True``. A driver may
return ``False`` only when another nominal owner records the authoritative
history transition. This hook coordinates history; it does not make the
generic service parse domain source or infer state ownership.

Integration
-----------

``BaseManagedWindow`` and ``BaseFormDialog`` expose an optional
``window_code_document_driver()``. ``WindowManager`` receives the capability
when registering the window. Windows without code mode return ``None``.

``AbstractManagerWidget`` and the simple code editor provide reusable driver
adapters. More specialized callers may implement the abstract driver directly,
but should keep their parser, renderer, and application semantics at the
domain owner.

Extension rules
---------------

* Keep the generic driver limited to read, validate, apply, revision, and
  history-coordination capabilities.
* Validate before mutation and apply through the same authoritative state path
  as the normal UI.
* Do not teach ``WindowManager`` variable names, AST shapes, or document-specific
  fallback rules.
* Do not duplicate the document in a second generic cache. Use ObjectState or a
  concrete driver's explicit revision owner.

See :doc:`../responsive_layout_widgets` for placement of the View Code action
inside a semantic form header.
