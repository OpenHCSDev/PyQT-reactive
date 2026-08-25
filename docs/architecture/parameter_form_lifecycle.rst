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

Readiness
---------

Form construction is complete only after the root transaction has materialised
the form tree and run semantic finalisation. Callers can inspect
``form_build_complete``, inspect ``form_build_failure`` after a failed build,
or subscribe to the one-shot ``form_build_completed`` signal. These public
lifecycle surfaces let host workflows wait for a usable form without guessing
from elapsed time or widget counts.

State updates
-------------

Widget edits are normalized through the form value contracts and written to
ObjectState. Field-change dispatch then coordinates local styling, nested views,
and path-scoped cross-window refresh. Resolved-value callbacks update inherited
placeholders without materializing them as explicit edits.

Code-driven form updates use the same declared type conversion as widget edits.
For ``Callable`` annotations, callable objects remain callable objects, including
callable-plus-keyword-argument entries inside a function pattern. The form
service rejects non-callable values instead of attempting to reconstruct a
function from its runtime type name.

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

Closing a root form calls ``ParameterFormManager.dispose()``. The manager
cancels its root construction transaction before disconnecting state callbacks
and cross-window registrations, so a retained but hidden Qt window cannot keep
building rows or publish a late failure. The ObjectState may outlive the window
when it is registered for reuse by another view.

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
