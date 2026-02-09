Field Styling and Visual Indicators Architecture
===============================================

**Centralized documentation for `*` and `_` visual indicators, provenance navigation, and reset button styling.**

This document provides the single source of truth for how pyqt-reactive displays visual indicators on form fields, reset buttons, and provenance navigation elements.

Overview
--------

Parameter forms use visual indicators to communicate field state to users:

- **Asterisk (*)** - Field has unsaved changes (resolved value differs from saved)
- **Underline (_)** - Field has explicit value (differs from signature default)
- **Caret (^)** - Provenance navigation available (field inherits from ancestor)
- **"Reset" button** - Can reset field to default, with * and _ indicators showing state

Visual Semantics
----------------

Two independent boolean indicators computed per field:

.. list-table::
   :header-rows: 1
   :widths: 15 20 65

   * - Indicator
     - Source
     - Meaning
   * - ``*`` (asterisk)
     - ``state.dirty_fields``
     - Resolved value differs from saved resolved value. Unsaved changes exist.
   * - ``_`` (underline)
     - ``state.signature_diff_fields``
     - Raw value differs from signature default. User has explicitly set a value.

These indicators are **orthogonal**:

- A field can be dirty (``*``) without differing from signature (e.g., edited then reverted)
- A field can differ from signature (``_``) without being dirty (e.g., saved explicit value)
- Both can be present (``*_``) or neither

Computing Indicators
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from pyqt_reactive.utils.styling_utils import get_field_indicators

    # Get both indicators for a field
    has_star, has_underline = get_field_indicators(
        state=manager.state,
        field_id=manager.field_id,  # e.g., "fiji_streaming_config"
        param_name="enabled"          # e.g., "enabled"
    )
    # Returns: (bool, bool)

The ``dotted_path`` is constructed as:

.. code-block:: python

    dotted_path = f'{field_id}.{param_name}' if field_id else param_name
    # "fiji_streaming_config.enabled" or just "enabled"

Where Visual Indicators Appear
------------------------------

Field Labels
~~~~~~~~~~~~

**Implementation**: `LabelWithHelp.set_dirty_indicator()` and `set_underline()`

- ``*`` prefix on label text
- Font underline for ``_``
- Updated via `_update_label_styling()` in `parameter_form_manager.py`

Reset Buttons
~~~~~~~~~~~~~

**Implementation**: `update_reset_button_styling()` in `styling_utils.py`

- ``*`` prefix on "Reset" text
- Font underline for ``_``
- Shows if the **target field** has indicators (not the button itself)

Provenance Navigation Button
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Implementation**: `ProvenanceButton` class in `clickable_help_components.py`

- Shows/hides based on ``_has_provenance()`` check
- Only clickable when provenance exists
- Not an indicator on the field, but availability of navigation

Update Triggers
---------------

When Field Value Changes (Normal Edit)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Flow**: Widget change → `FieldChangeDispatcher.dispatch()`

1. User edits widget value
2. Widget emits change signal
3. `FieldChangeEvent` created and dispatched
4. `state.update_parameter()` called
5. **Updates triggered**:
   - Sibling placeholder refresh
   - Enabled field styling (if applicable)
   - **Reset button styling** (all reset buttons in manager)
   - **Provenance button visibility** (if in groupbox title)
6. Local signal emission: `parameter_changed`

**Code**:

.. code-block:: python
    :caption: field_change_dispatcher.py

    # Update reset button styling for ALL reset buttons in this manager
    from pyqt_reactive.utils.styling_utils import update_reset_button_styling
    for field_name, reset_button in source.reset_buttons.items():
        update_reset_button_styling(reset_button, source.state, source.field_id, field_name)

When Field is Reset (Individual)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Flow**: `reset_parameter()` → `_update_label_styling()` → `_update_reset_button_styling()`

1. User clicks reset button
2. `reset_parameter(param_name)` called
3. `state.update_parameter()` with None/reset value
4. `FieldChangeDispatcher.dispatch()` called
5. `_update_label_styling(param_name)` called (updates label)
6. `_update_reset_button_styling(param_name)` called (updates reset button)
7. `_update_provenance_button_visibility()` called (updates provenance button)

**Why separate updates?** The dispatcher runs for ALL field changes, but individual reset needs immediate visual feedback. The styling updates ensure consistency even if dispatcher has slight delay.

**Code**:

.. code-block:: python
    :caption: parameter_form_manager.py

    def reset_parameter(self, param_name: str) -> None:
        # ... reset logic ...
        event = FieldChangeEvent(param_name, reset_value, self, is_reset=True)
        FieldChangeDispatcher.instance().dispatch(event)
        
        # Update label styling after reset
        self._update_label_styling(param_name)
        
        # Update reset button styling
        self._update_reset_button_styling(param_name)
        
        # Update provenance button visibility
        self._update_provenance_button_visibility()

When All Fields Reset (Reset All)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Flow**: `reset_all_parameters()` → batch reset → final styling update

1. User clicks "Reset All" button
2. `reset_all_parameters()` called
3. Loop: calls `reset_parameter()` for each parameter
4. Single placeholder refresh at end (optimization)
5. **Loop**: Update all reset button styling
6. Single provenance button update

**Optimization**: Reset button and provenance updates happen ONCE at the end instead of per-parameter, since `reset_parameter()` already updates during the loop.

**Code**:

.. code-block:: python
    :caption: parameter_form_manager.py

    def reset_all_parameters(self) -> None:
        # ... batch reset logic ...
        
        # Update all reset buttons and provenance button once at the end
        for param_name in param_names:
            self._update_reset_button_styling(param_name)
        self._update_provenance_button_visibility()

Shared Utilities
----------------

styling_utils.py
~~~~~~~~~~~~~~~~

Centralized styling logic to avoid duplication:

.. code-block:: python
    :caption: src/pyqt_reactive/utils/styling_utils.py

    def get_field_indicators(state, field_id, param_name):
        """Returns (has_star, has_underline) for a field."""
        path = f'{field_id}.{param_name}' if field_id else param_name
        return (path in state.dirty_fields, path in state.signature_diff_fields)

    def update_reset_button_styling(button, state, field_id, field_name):
        """Apply * and _ styling to a reset button."""
        has_star, has_underline = get_field_indicators(state, field_id, field_name)
        
        # Update text with * prefix
        text = "Reset"
        if has_star:
            text = "*" + text
        button.setText(text)
        
        # Apply underline via font (doesn't affect other button styles)
        font = button.font()
        font.setUnderline(has_underline)
        button.setFont(font)

Architecture Rationale
----------------------

Why Two Update Paths?
~~~~~~~~~~~~~~~~~~~~~

1. **FieldChangeDispatcher**: Catches ALL changes including user edits, sibling inheritance updates, cross-window changes
2. **reset_parameter()**: Ensures immediate visual feedback for reset operations, handles batch reset optimization

Why Font Underline Instead of CSS?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

CSS ``text-decoration: underline`` via ``setStyleSheet()`` **replaces** all existing button styles. Using ``setFont()`` with underline:

- Preserves hover/pressed styling from ``_apply_reset_button_style()``
- Only modifies the underline attribute
- Works across all button states

Why Provenance Button Uses Visibility?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Unlike labels and reset buttons which are always visible with indicators, the provenance button:

- Should be **hidden** when no provenance available (cleaner UI)
- Uses ``_has_provenance()`` which checks ``state.get_provenance(dotted_path)``
- Updates both at creation and on field changes

Related Documentation
---------------------

- :doc:`field_change_dispatcher` - Event dispatch flow and sibling inheritance
- :doc:`parameter_form_lifecycle` - Form lifecycle including reset operations
- :doc:`list_item_preview_system` - List item * and _ semantics (similar concept)
