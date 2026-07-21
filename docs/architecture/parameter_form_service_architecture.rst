Parameter-form services
=======================

``ParameterFormManager`` coordinates an ObjectState-backed object, introspected
parameter metadata, widget creation, value collection, reset/help operations,
and chrome synchronization.

Core ownership
--------------

``pyqt_reactive.forms``
  Owns form structure, parameter info types, widget strategies, dispatch, and
  the manager lifecycle.

``pyqt_reactive.services``
  Owns reusable operations such as parameter help/reset, field dispatch,
  styling, scope tokens, signals, and polling.

ObjectState
  Owns editing, scope resolution, snapshots, provenance, and time travel.

Host application
  Owns which objects are editable, exclusions, function catalogs, component
  selectors, code generation, and domain validation.

Service construction uses explicit configuration and protocols. A generic
service must not import a host module or branch on host field names. See
:doc:`parameter_form_lifecycle` and
:doc:`widget_protocol_system`.

