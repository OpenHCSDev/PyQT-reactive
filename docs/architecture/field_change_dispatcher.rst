Field-change dispatcher
=======================

``pyqt_reactive.services.field_change_dispatcher.FieldChangeDispatcher`` is the
generic boundary between form edits and interested UI projections.

An event carries the changed ObjectState/form manager and a normalized field
path. Subscribers register against explicit scope/type predicates and receive
only matching events. The dispatcher does not resolve domain configuration or
infer relationships from class-name strings.

Dispatch is synchronous at the state boundary; UI refresh may be debounced by a
consumer. Reentrancy guards prevent a refresh from publishing the same logical
change again. Subscribers must unregister on teardown so closed windows do not
retain managers.

See :doc:`cross_window_update_optimization` and
:doc:`parameter_form_lifecycle`.

