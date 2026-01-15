State Management
================

This page documents how pyqt-reactor manages form state and integrates with ObjectState
for hierarchical configuration management.

Form State Management
---------------------

Purpose
~~~~~~~
pyqt-reactor manages form state through the ``ParameterFormManager`` and ``FieldChangeDispatcher``.
Forms are automatically generated from dataclasses and maintain bidirectional binding with
the underlying data model.

Key Components
~~~~~~~~~~~~~~

**ParameterFormManager**
  - Generates PyQt6 forms from dataclass definitions
  - Manages widget creation and layout
  - Collects and validates user input
  - Integrates with ObjectState for lazy configuration

**FieldChangeDispatcher**
  - Broadcasts field changes across the form
  - Enables reactive updates when one field changes
  - Supports conditional field visibility and enablement
  - Triggers validation and preview updates

**ValueCollectionService**
  - Gathers current values from all widgets
  - Handles type conversion and validation
  - Returns typed dataclass instances

ObjectState Integration
----------------------

Purpose
~~~~~~~
pyqt-reactor integrates with ObjectState to support lazy configuration and hierarchical
inheritance. Forms can display placeholder text showing inherited values from parent contexts.

Key Features
~~~~~~~~~~~~
- **Lazy Resolution**: Fields with ``None`` values inherit from context hierarchy
- **Provenance Tracking**: UI shows where each value comes from (global, pipeline, step)
- **Placeholder Text**: Empty fields display inherited values as placeholders
- **Dirty Tracking**: Automatic detection of unsaved changes
- **Undo/Redo**: Git-style history with branching timelines

Integration Pattern
~~~~~~~~~~~~~~~~~~~
When a form is created from a dataclass with ObjectState context:

1. Form widgets are created for each field
2. Placeholder text shows inherited values from parent scopes
3. User edits update ObjectState's live parameters
4. Dirty fields are tracked automatically
5. Save commits changes to ObjectState baseline

Widget Protocols
----------------

Purpose
~~~~~~~
pyqt-reactor uses ABC-based protocols to define type-safe widget contracts. This eliminates
duck typing in favor of explicit, fail-loud inheritance-based architecture.

Core Protocols
~~~~~~~~~~~~~~

**ValueGettable**
  - Widgets that can return their current value
  - Method: ``get_value() -> Any``

**ValueSettable**
  - Widgets that can accept a new value
  - Method: ``set_value(value: Any) -> None``

**PlaceholderCapable**
  - Widgets that display placeholder text for inherited values
  - Method: ``set_placeholder_text(text: str) -> None``

**RangeConfigurable**
  - Widgets with min/max constraints (spinboxes, sliders)
  - Methods: ``set_minimum()``, ``set_maximum()``

**EnumSelectable**
  - Widgets that display enum options (comboboxes)
  - Method: ``set_enum_values(values: List[str]) -> None``

**ChangeSignalEmitter**
  - Widgets that emit signals when values change
  - Signal: ``value_changed``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The registry coordinates saved/live baselines across all ObjectStates so that
application code can distinguish "proposed" vs "committed" values while showing
immediate UI feedback.

Notes
~~~~~
- Registry methods are classmethods; the registry is effectively a singleton.
- History/undo is covered separately in :doc:`undo_redo`.
