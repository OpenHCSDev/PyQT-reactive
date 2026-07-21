Tabbed form pattern
===================

``TabbedFormWidget`` groups several field-scoped parameter forms that share one
``ObjectState``.  Tabs are declarative display groupings; they are not a registry
of application configuration types.

``TabConfig`` contains ``name``, ``field_ids``, and optional ``icon`` and
``tooltip`` values.  ``TabbedFormConfig`` contains ``tabs`` plus optional
``shared_field_ids``, ``color_scheme``, ``use_scroll_area``, and
``header_widgets``.

.. code-block:: python

   from pyqt_reactive.widgets.shared.tabbed_form_widget import (
       TabConfig,
       TabbedFormConfig,
       TabbedFormWidget,
   )

   tab_config = TabbedFormConfig(
       shared_field_ids=["name"],
       tabs=[
           TabConfig(
               name="Input",
               field_ids=["input.path", "input.pattern"],
           ),
           TabConfig(
               name="Output",
               field_ids=["output.directory"],
               tooltip="Output settings",
           ),
       ],
   )
   widget = TabbedFormWidget(state=object_state, config=tab_config)

Each field ID is a canonical dotted path owned by the ObjectState model.  The
widget creates child ``ParameterFormManager`` instances with those paths and
aggregates their ``parameter_changed`` signals.  pyqt-reactive does not infer a
tab's meaning from field names or import concrete host configuration classes.

See :doc:`parameter_form_lifecycle` and
:doc:`field_change_dispatcher`.

