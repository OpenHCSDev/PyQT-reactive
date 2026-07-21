List item preview system
========================

Manager widgets can describe rich list rows with ``ListItemFormat``.  The
declaration contains ObjectState field paths; the shared display builder resolves
and formats those paths without knowing the host application's domain types.

Declarative format
------------------

``ListItemFormat`` is defined in
``pyqt_reactive.widgets.shared.manager_item_display_builder`` and has five
fields:

.. list-table::
   :header-rows: 1

   * - Field
     - Meaning
   * - ``first_line``
     - Field paths rendered after the item name.
   * - ``preview_line``
     - Field paths rendered on the preview line.
   * - ``detail_line_field``
     - Optional field path used as the detail line.
   * - ``formatters``
     - Per-path format strings or callables.
   * - ``append_signature_diff_fields``
     - Whether fields that differ from their callable signature are appended.

.. code-block:: python

   from pyqt_reactive.widgets.shared.abstract_manager_widget import (
       AbstractManagerWidget,
   )
   from pyqt_reactive.widgets.shared.manager_item_display_builder import (
       ListItemFormat,
   )

   class JobManagerWidget(AbstractManagerWidget):
       LIST_ITEM_FORMAT = ListItemFormat(
           first_line=("worker_count",),
           preview_line=("storage.backend", "filters.pattern"),
           detail_line_field="output_path",
           formatters={
               "worker_count": lambda value: f"workers:{value}",
           },
           append_signature_diff_fields=True,
       )

There is no ``show_config_indicators`` field.  Domain-specific indicators are
ordinary segments supplied by the owning manager or formatting strategy.

Rendering flow
--------------

``_ManagerItemDisplayBuilder`` resolves the item's scope through
``ObjectStateRegistry``, then builds a structured ``StyledTextLayout``.  Field
paths remain attached to ``Segment`` objects so the delegate can apply dirty and
signature-difference styling without parsing rendered strings.

The builder also discovers fields declared always-viewable by ObjectState's lazy
metadata.  When ``append_signature_diff_fields`` is enabled, it appends missing
signature-difference paths while avoiding fields already represented by a
parent or child path.

Ownership boundary
------------------

pyqt-reactive owns structured row construction and painting.  ObjectState owns
field values and lazy metadata.  The host manager owns which semantic fields to
show, field abbreviations, status prefixes, and custom formatters.  Keep those
declarations on the manager or domain type instead of adding concrete names to
the generic builder.

See also :doc:`abstract_manager_widget` and
:doc:`gui_performance_patterns`.
