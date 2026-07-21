Abstract table browser ownership
================================

``AbstractTableBrowser`` owns the generic table, search, presentation, and
declared-column filtering pipeline for browser-style widgets. A consumer
declares row semantics and may contribute domain context, but it does not
rebuild generic filter or column-configuration UI.

Authoritative columns
---------------------

``ColumnDef`` is the column declaration. Its ``key`` is the stable semantic
identity used by presentation and filter state; the visible ``name`` is only a
label.

.. code-block:: python

   from pyqt_reactive.widgets.shared.abstract_table_browser import ColumnDef

   columns = [
       ColumnDef("Name", "name", width=220),
       ColumnDef("Category", "category", filterable=True),
       ColumnDef(
           "Tags",
           "tags",
           filterable=True,
           filter_values=lambda item: item.tags,
       ),
   ]

``filter_values`` is optional. Without it, the generic filter reads the value
at the column's row-data index. With it, one row may expose several normalized
values. Consumers should not duplicate this declaration in a separate filter
schema.

Column presentation
-------------------

``ColumnPresentation`` stores ordered and hidden column keys.
``ColumnPresentationState`` is the shared runtime owner that resolves those
preferences against the current ``ColumnDef`` declarations and projects them
onto both the table header and the filter panel.

Presentation preferences deliberately survive dynamic schemas:

* absent keys remain in the preference so a temporarily missing column can
  recover its prior position;
* newly declared keys append in declaration order;
* every current ``ColumnDef.key`` must be unique; and
* persistence remains outside the generic widget. A host can initialize the
  state and persist ``preference_changed`` through its typed settings owner.

Users edit order and visibility through ``ColumnPresentationDialog``. Moving a
Qt header section updates the same presentation owner; it is not a second order
model.

Filtering pipeline
------------------

The browser composes filters in one direction:

.. code-block:: text

   all_items
       -> external/base projection
       -> active declared-column filters
       -> filtered_items and rendered rows

``set_items()`` replaces the authoritative item collection and rebuilds the
declared filter choices. ``set_filtered_items()`` supplies a search, tree,
folder, or other domain-owned base projection. Generic column filters then
apply to that projection.

Programmatic consumers use ``set_column_filter_selection()``,
``column_filter_selection()``, and ``is_column_filter_active()`` by semantic
column key. They do not reach into checkbox widgets.

Visibility and filtering are independent. Hiding a column does not clear its
active filter. The filter panel retains that semantic selection and reports
hidden active filters so a presentation edit cannot silently change the item
set.

Context, filters, and table layout
----------------------------------

The content area is a horizontal split between the filter side and the table.
Within the filter side, ``set_column_filter_context_widget()`` places an
optional domain-owned context widget above the generic filter panel in a
vertical splitter:

.. code-block:: text

   content_splitter (horizontal)
   +-- column_filter_splitter (vertical)
   |   +-- optional domain context
   |   +-- generic column filters
   +-- table

This hook is for spatial context such as a navigation tree. The consumer still
does not own filter construction, presentation state, or the table/filter
composition.

Subclass contract
-----------------

A concrete browser supplies row semantics:

.. code-block:: python

   class ItemBrowser(AbstractTableBrowser[Item]):
       def get_columns(self):
           return columns

       def extract_row_data(self, item):
           return [item.name, item.category, ", ".join(item.tags)]

       def get_searchable_text(self, item):
           return f"{item.name} {item.category} {' '.join(item.tags)}"

Use ``reconfigure_columns()`` when a dynamic declaration changes. The browser
publishes the new declarations to ``ColumnPresentationState``, reapplies order
and visibility, rebuilds filter choices, and repopulates the current items.

Selection ownership
-------------------

``TableSelectionMode.SINGLE`` and ``TableSelectionMode.MULTI`` map to Qt row
selection modes. Selection signals carry semantic item keys, and
``select_key()`` or ``select_keys()`` restores selection without consumers
depending on the current row order.

Extension rules
---------------

* Treat ``ColumnDef.key`` as stable application data.
* Declare filter semantics on ``ColumnDef`` rather than building parallel
  checkbox lists in a consumer.
* Feed domain filters through ``set_filtered_items()`` and let the browser
  compose the generic column filters.
* Persist only the immutable ``ColumnPresentation`` through a typed host-owned
  setting; do not make pyqt-reactive aware of a domain settings type.
* Contribute domain context with ``set_column_filter_context_widget()`` rather
  than reparenting the generic filter panel.

See also
--------

* :doc:`form_scroll_containment` for scrollbar and viewport ownership.
* :doc:`widget_protocol_system` for generated-widget protocol boundaries.
