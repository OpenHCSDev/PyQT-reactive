Cross-window updates
====================

Multiple forms may project related ObjectState scopes. pyqt-reactive propagates
typed field-change events and refreshes only managers whose declared scope can
be affected.

``FieldChangeDispatcher`` owns event routing. Form managers own their current
ObjectState and field tree. Cross-window preview mixins translate a changed
field path into affected presentation keys. Debounce and dispatch-cycle caches
coalesce repeated Qt signals without changing the underlying state authority.

The host supplies scope identities and relationships. Generic services must not
recognize host configuration class names or maintain a copied dependency table.
When inheritance semantics change, extend ObjectState or the host's declared
scope adapter rather than adding a field-name exception here.

See :doc:`field_change_dispatcher` and
:doc:`parameter_form_lifecycle`.

