State integration
=================

pyqt-reactive owns the PyQt projection of editable state. ObjectState owns the
underlying values, resolved inheritance, dirty tracking, provenance, snapshots,
and history.

Form boundary
-------------

``ParameterFormManager`` is constructed from an existing ``ObjectState``:

.. code-block:: python

   from dataclasses import dataclass

   from objectstate import ObjectState
   from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager

   @dataclass
   class Settings:
       name: str = "default"
       count: int = 4

   state = ObjectState(Settings(), scope_id="settings")
   form = ParameterFormManager(state)

The manager reads raw and resolved values from the state, builds widgets,
projects inherited values as UI previews, and writes edits back through the
state's parameter API. Multiple views over one logical object should receive the
same registered state.

Field dispatch
--------------

``FieldChangeDispatcher`` is an internal singleton coordinator used by form
managers. Its pipeline:

1. writes the source field through ObjectState;
2. refreshes affected placeholder previews;
3. updates enabled-field chrome;
4. emits the root manager's ``parameter_changed`` signal; and
5. publishes cross-window context changes when the state permits them.

Applications subscribe to ``ParameterFormManager.parameter_changed``. They
should not instantiate a second dispatcher or mirror ObjectState parameters in
widget-owned dictionaries.

Placeholder capability
----------------------

Placeholder rendering is an explicit widget capability. Before applying a
placeholder, generic form code asks
``PyQt6WidgetEnhancer.supports_placeholder(widget)``:

.. code-block:: python

   from PyQt6.QtWidgets import QLineEdit
   from pyqt_reactive.forms.widget_strategies import PyQt6WidgetEnhancer

   editor = QLineEdit()
   if PyQt6WidgetEnhancer.supports_placeholder(editor):
       PyQt6WidgetEnhancer.apply_placeholder_text(
           editor,
           "Inherited value: default",
       )

``supports_placeholder`` returns true when either:

- the widget implements ``ResolvedValuePreviewSettable``; or
- the widget's exact type has a registered placeholder strategy.

This check is distinct from ``has_placeholder_state``. Support answers whether
the widget can render a preview; state answers whether placeholder chrome or
cached placeholder data is currently present. Unsupported widgets fail loudly
if placeholder application is attempted.

Ownership
---------

- ObjectState owns editing semantics and history.
- pyqt-reactive owns widget creation, projection, signals, and reusable UI
  services.
- The host owns domain validation, lifecycle, configuration topology, and when
  edits are saved or executed.

See :doc:`architecture/parameter_form_lifecycle`,
:doc:`architecture/widget_protocol_system`, and
`ObjectState documentation <https://objectstate.readthedocs.io>`_.
