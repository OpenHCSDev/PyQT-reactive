Abstract manager widgets
========================

``AbstractManagerWidget`` provides reusable list-management scaffolding for Qt
applications. It composes small controllers for selection, reordering, status,
previews, ObjectState binding, time travel, and UI construction.

Host applications supply item access and domain actions through the declared
manager hooks/protocols. The base widget owns the generic lifecycle:

1. build the list and action surface;
2. bind the selected item's ObjectState;
3. delegate add/edit/remove/reorder actions;
4. refresh only the affected display projection;
5. disconnect bindings when the widget closes.

Domain item types, pipeline semantics, and preview labels do not belong in this
package. A host subclasses the manager and implements the relevant hooks rather
than patching the base class with concrete names.

See :doc:`list_item_preview_system` and
:doc:`../development/ui-patterns`.
