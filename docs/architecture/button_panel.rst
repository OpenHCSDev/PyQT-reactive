Button Panel Component
======================

**Reusable button panel with declarative configuration.**

**Module**: ``pyqt_reactive.widgets.shared.button_panel``

Overview
--------

``ButtonPanel`` provides a reusable button panel component that can be used by any widget without requiring inheritance. It uses a declarative ``BUTTON_CONFIGS`` format for specifying buttons.

This component was extracted from ``AbstractManagerWidget`` to allow widgets to use the same button panel pattern without inheriting from the full manager class.

Architecture
------------

``ButtonPanel`` uses a simple declarative configuration:

.. code-block:: python

    BUTTON_CONFIGS = [
        ("Refresh", "refresh", "Refresh the display"),
        ("Toggle", "toggle_layout", "Toggle between layouts"),
        ("Export", "export", "Export data"),
    ]

Each button configuration is a tuple of:
- **label**: Button text (e.g., "Refresh")
- **action_id**: Identifier passed to callback (e.g., "refresh")
- **tooltip**: Tooltip text (e.g., "Refresh the display")

Usage
-----

Basic Usage
~~~~~~~~~~~

.. code-block:: python

    from pyqt_reactive.widgets.shared.button_panel import ButtonPanel
    from pyqt_reactive.theming import StyleSheetGenerator

    # Define button configurations
    BUTTON_CONFIGS = [
        ("Refresh", "refresh", "Refresh the display"),
        ("Toggle", "toggle_layout", "Toggle between layouts"),
        ("Export", "export", "Export data"),
    ]

    # Create button panel
    panel = ButtonPanel(
        button_configs=BUTTON_CONFIGS,
        on_action=self.handle_button_action,
        style_generator=self.style_generator,
    )

    # Add panel to layout
    layout.addWidget(panel)

Action Handler
~~~~~~~~~~~~~~~

The ``on_action`` callback receives the ``action_id`` from the clicked button:

.. code-block:: python

    def handle_button_action(self, action_id: str):
        """Handle button actions."""
        if action_id == "refresh":
            self.refresh_display()
        elif action_id == "toggle_layout":
            self.toggle_layout()
        elif action_id == "export":
            self.export_data()

Grid Layout
~~~~~~~~~~~~

By default, buttons are laid out in a single horizontal row. You can specify a grid layout:

.. code-block:: python

    panel = ButtonPanel(
        button_configs=self.BUTTON_CONFIGS,
        on_action=self.handle_button_action,
        grid_columns=2,  # 2 columns
    )

``grid_columns=0`` keeps every action in one horizontal row. A positive value
is the exact number of columns per complete row; the final row may be partial.
For the three actions above, ``grid_columns=2`` places Refresh and Toggle in the
first row and Export in the second. Placement follows declaration order.

Callback ownership
------------------

``on_action`` is required and is the only click-dispatch boundary. The panel
captures each declared ``action_id`` and invokes that callback directly; it does
not expose a parallel Qt signal.

.. code-block:: python

    class ActionsWidget(QWidget):
        def __init__(self, color_scheme=None, config=None, parent=None):
            super().__init__(parent)
            self.button_panel = ButtonPanel(
                button_configs=[
                    ("Refresh", "refresh", "Refresh the display"),
                ],
                on_action=self.handle_button_action,
                style_generator=self.style_generator,
            )

        def handle_button_action(self, action_id: str):
            if action_id == "refresh":
                self.refresh()

Appending a button
------------------

``add_button(action_id, button)`` appends an already constructed
``QPushButton`` using the panel's declared row/grid policy, stores it under its
exact action ID, and returns the button. Duplicate action IDs raise
``ValueError``. The caller owns connecting a dynamically added button to the
panel's ``on_action`` callback when that behavior is required; ``add_button``
owns placement and identity, not a second dispatch mechanism.

Manager title actions use ``FormWindowActionHeader`` and
``StagedWrapLayout`` when capacity-based wrapping is required. That compositor
groups stable action widgets and right-aligns declared groups; ``ButtonPanel``
continues to own grid placement and callback dispatch. Neither component copies
the other's action list.

Styling
-------

``ButtonPanel`` integrates with ``StyleSheetGenerator`` for consistent styling:

.. code-block:: python

    from pyqt_reactive.theming import StyleSheetGenerator, ColorScheme

    color_scheme = ColorScheme()
    style_generator = StyleSheetGenerator(color_scheme)

    panel = ButtonPanel(
        button_configs=self.BUTTON_CONFIGS,
        on_action=self.handle_button_action,
        style_generator=style_generator,  # Apply styles
    )

Migration from AbstractManagerWidget
------------------------------------

Before (AbstractManagerWidget):

.. code-block:: python

    class MyWidget(AbstractManagerWidget):
        """Widget with button panel."""

        BUTTON_CONFIGS = [
            ("Refresh", "refresh", "Refresh the display"),
        ]

        def __init__(self):
            super().__init__()
            # Button panel created automatically by AbstractManagerWidget

After (ButtonPanel):

.. code-block:: python

    class MyWidget(QWidget):
        """Widget with button panel."""

        def __init__(self):
            super().__init__()

            # Create button panel manually
            self.button_panel = ButtonPanel(
                button_configs=[
                    ("Refresh", "refresh", "Refresh the display"),
                ],
                on_action=self.handle_button_action,
            )

        def handle_button_action(self, action_id: str):
            if action_id == "refresh":
                self.refresh()

Benefits
---------

- **No inheritance required**: Use with any widget class
- **Declarative configuration**: Define buttons in a list
- **Flexible layout**: Single row or grid layout
- **Consistent styling**: Integrates with StyleSheetGenerator
- **Action-based**: Simple callback interface with action IDs

See Also
--------

- :doc:`abstract_manager_widget` - Abstract manager widget (original button panel location)
- :doc:`../responsive_layout_widgets` - Responsive layout components
- :doc:`system_monitor` - System monitor usage example
