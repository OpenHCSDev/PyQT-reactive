Parameter-form lifecycle
========================

``ParameterFormManager`` is a QWidget view over one authoritative
``ObjectState``. It does not own a second configuration model.

Construction
------------

1. The caller creates or retrieves an ``ObjectState`` for the edited object.
2. It passes that state and a ``FormManagerConfig`` to
   ``ParameterFormManager``.
3. The manager derives typed form structure through python-introspect and the
   widget strategy registry.
4. Form services build widgets, connect signals, and project resolved state.
5. Nested dataclasses receive nested managers tied to the same root state.

State updates
-------------

Widget edits are normalized through the form value contracts and written to
ObjectState. Field-change dispatch then coordinates local styling, nested views,
and path-scoped cross-window refresh. Resolved-value callbacks update inherited
placeholders without materializing them as explicit edits.

Cross-window lifetime
---------------------

Root managers subscribe to their state's materialized and resolved changes.
Signal registration must last exactly as long as the manager. Nested managers
belong to their root window and do not independently join the global
cross-window set.

Asynchronous work
-----------------

Large forms may create widgets progressively. Expensive placeholder or help
resolution can run outside the GUI thread, but applying widget changes must
return to the Qt thread. Debouncing coalesces rapid state notifications.

Teardown
--------

Closing a root form disconnects state callbacks, signal-service registrations,
timers, and nested managers. The ObjectState may outlive the window when it is
registered for reuse by another view.

Ownership boundary
------------------

ObjectState owns values, resolution, hierarchy, dirty state, and history.
pyqt-reactive owns generic form/view lifecycle. Host applications own domain
configuration types, window workflows, and code/UI round trips.

See also
--------

- :doc:`parameter_form_service_architecture`
- :doc:`field_change_dispatcher`
- :doc:`widget_protocol_system`
- `ObjectState documentation <https://objectstate.readthedocs.io>`_
