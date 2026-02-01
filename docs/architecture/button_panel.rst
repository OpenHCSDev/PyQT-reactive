Button Panel Component
=====================

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
~~~~~~~~~~

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

This creates a grid with the specified number of columns:

.. list-table::
   :header-rows: 1

   * - grid_columns
     - Layout
   * - 0
     - Single horizontal row
   * - 1
     - Single vertical column
   * - 2
     - 2x2 grid
   * - 3
     - 3x2 grid
   * - 4
     - 4x2 grid

Integration with SystemMonitor
---------------------------

``SystemMonitor`` uses ``ButtonPanel`` for its action buttons:

.. code-block:: python

    class SystemMonitorWidget(QWidget):
        """System Monitor Widget."""

        # Declarative button configuration
        BUTTON_CONFIGS = [
            ("Global Config", "global_config", "Open global configuration editor"),
            ("Log Viewer", "log_viewer", "Open log viewer window"),
            ("Custom Functions", "custom_functions", "Manage custom functions"),
            ("Test Plate", "test_plate", "Generate synthetic test plate"),
        ]

        BUTTON_GRID_COLUMNS = 0  # Single row

        def __init__(self, color_scheme=None, config=None, parent=None):
            super().__init__(parent)

            # Create button panel
            self.button_panel = ButtonPanel(
                button_configs=self.BUTTON_CONFIGS,
                style_generator=self.style_generator,
                grid_columns=self.BUTTON_GRID_COLUMNS,
            )

            # Connect actions
            self.button_panel.action_triggered.connect(self.handle_button_action)

        def handle_button_action(self, action_id: str):
            """Handle button panel actions."""
            if action_id == "global_config":
                self.show_global_config.emit()
            elif action_id == "log_viewer":
                self.show_log_viewer.emit()
            # ... etc

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

Signals
-------

**action_triggered** (pyqtSignal)

Emitted when a button is clicked. Provides the ``action_id``:

.. code-block:: python

    panel.action_triggered.connect(lambda action_id: print(f"Action: {action_id}"))

Migration from AbstractManagerWidget
----------------------------------

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
- :doc:`responsive_layout_widgets` - Responsive layout components
- :doc:`system_monitor` - System monitor usage example
