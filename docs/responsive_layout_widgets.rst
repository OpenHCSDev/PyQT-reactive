Responsive Layout Widgets
=========================

Responsive layout widgets provide adaptive UI layouts that automatically adjust to available window space, enabling compact window designs without horizontal scrolling.

Overview
--------

The responsive layout system addresses the common problem of form UIs becoming too wide for comfortable viewing on smaller screens or when multiple windows are tiled. The system provides automatic wrapping behavior that switches between horizontal and vertical layouts based on available space.

Key Features
~~~~~~~~~~~~

- **Automatic wrapping**: Widgets automatically wrap to a second row when content exceeds available width
- **Smart content detection**: Uses font metrics to calculate actual text width, not just widget size hints
- **Configurable thresholds**: Customizable width thresholds for switching between layouts
- **Global enable/disable**: System-wide toggle for responsive wrapping behavior
- **Layout preservation**: Maintains visual hierarchy and spacing during layout transitions
- **Zero runtime overhead**: Layout calculations only occur on resize events

Architecture
------------

The responsive layout system consists of three main components:

ResponsiveTwoRowWidget
~~~~~~~~~~~~~~~~~~~~~~

The base class providing two-row layout switching. It maintains two internal rows:

- **Row 1**: Always visible, contains left-aligned widgets
- **Row 2**: Appears only when wrapping is triggered, contains right-aligned widgets

Switching Logic
^^^^^^^^^^^^^^^

The switch between horizontal and vertical modes follows this algorithm:

1. Calculate total content width needed for all widgets in a single row
2. Compare against available parent width
3. Switch to vertical mode when ``available_width < content_width``
4. Switch back to horizontal when ``available_width > (content_width + 20)``

The 20-pixel buffer prevents rapid switching when hovering near the threshold.

Content Width Calculation
^^^^^^^^^^^^^^^^^^^^^^^^^

The system calculates actual content width accounting for:

- Label text width (using font metrics)
- Widget size hints
- Layout spacing and margins
- Content-based minimum sizes

ResponsiveParameterRow
~~~~~~~~~~~~~~~~~~~~~~

Specialized for ParameterFormManager parameter rows. Automatically configures:

- Labels as left widgets with ``Preferred`` size policy and word wrap enabled
- Input widgets as right widgets with ``Expanding`` size policy
- Reset buttons as right widgets with minimal stretch

ResponsiveGroupBoxTitle
~~~~~~~~~~~~~~~~~~~~~~~

Provides responsive title layouts for :class:`GroupBoxWithHelp`. The title widget switches between:

**Horizontal Mode**::

  [Title] [Help] [Inline Widgets]          [Right Widgets]

**Vertical Mode**::

  [Title]
  [Help] [Inline Widgets]                  [Right Widgets]

The title widget maintains separate storage for:

- Title widget (always in row 1)
- Help button (moves to row 2 when wrapping)
- Inline widgets (stay with title)
- Right widgets (always right-aligned)

Usage
-----

Global Toggle
~~~~~~~~~~~~~

Enable or disable responsive wrapping system-wide:

.. code-block:: python

   from pyqt_reactive.widgets.shared.responsive_layout_widgets import (
       set_wrapping_enabled, is_wrapping_enabled
   )
   from pyqt_reactive.widgets.shared.responsive_groupbox_title import (
       set_wrapping_enabled as set_gb_wrapping
   )
   
   # Enable parameter row wrapping
   set_wrapping_enabled(True)
   
   # Enable GroupBox title wrapping  
   set_gb_wrapping(True)
   
   # Check current state
   if is_wrapping_enabled():
       print("Responsive wrapping is active")

ParameterFormManager Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When wrapping is enabled, ParameterFormManager automatically uses ResponsiveParameterRow:

.. code-block:: python

   from dataclasses import dataclass
   from pyqt_reactive.forms import ParameterFormManager
   from pyqt_reactive.widgets.shared.responsive_layout_widgets import set_wrapping_enabled
   
   @dataclass
   class ProcessingConfig:
       long_description_field_name: str = "default"
       another_parameter: int = 10
   
   # Enable responsive wrapping before creating forms
   set_wrapping_enabled(True)
   
   form = ParameterFormManager(ProcessingConfig)
   # Parameter rows will now wrap when window is narrow

Manual Widget Creation
~~~~~~~~~~~~~~~~~~~~~~

Create responsive containers directly:

.. code-block:: python

   from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton
   from pyqt_reactive.widgets.shared.responsive_layout_widgets import (
       ResponsiveParameterRow, set_wrapping_enabled
   )
   
   app = QApplication([])
   set_wrapping_enabled(True)
   
   # Create responsive row
   row = ResponsiveParameterRow(width_threshold=150, parent=parent_widget)
   
   # Add widgets
   label = QLabel("Parameter Name:")
   input_field = QLineEdit()
   reset_btn = QPushButton("Reset")
   
   row.set_label(label)
   row.set_input(input_field)
   row.set_reset_button(reset_btn)
   
   # Add to parent layout
   parent_layout.addWidget(row)

GroupBoxWithHelp Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When wrapping is enabled, GroupBoxWithHelp automatically uses ResponsiveGroupBoxTitle:

.. code-block:: python

   from pyqt_reactive.widgets.shared.clickable_help_components import GroupBoxWithHelp
   from pyqt_reactive.widgets.shared.responsive_groupbox_title import set_wrapping_enabled
   
   set_wrapping_enabled(True)
   
   groupbox = GroupBoxWithHelp(
       title="Processing Configuration",
       help_target=ProcessingConfig,
       color_scheme=color_scheme
   )
   
   # Add control buttons - they will automatically move to row 2 when narrow
   groupbox.addTitleWidget(reset_all_button)
   groupbox.addTitleWidget(enabled_checkbox)

TabbedFormWidget with Tear-Off Tabs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Combine responsive layouts with tear-off tabs for flexible window management:

.. code-block:: python

   from pyqt_reactive.widgets.shared.tabbed_form_widget import TabbedFormWidget
   from pyqt_reactive.widgets.shared.responsive_layout_widgets import set_wrapping_enabled
   
   set_wrapping_enabled(True)
   
   tabbed = TabbedFormWidget(config=tab_config)
   # Tabs can be torn off and docked elsewhere while maintaining responsive layouts

API Reference
-------------

ResponsiveTwoRowWidget
~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: ResponsiveTwoRowWidget(width_threshold=400, parent=None, layout_config=None)
   
   Base class for two-row responsive layouts.
   
   :param width_threshold: Minimum width before wrapping triggers (default: 400)
   :param parent: Parent widget
   :param layout_config: Layout configuration object for spacing/margins
   
   .. py:method:: add_left_widget(widget, stretch=0)
      
      Add widget to left side (stays in row 1).
      
      :param widget: Widget to add
      :param stretch: Stretch factor for layout
   
   .. py:method:: add_right_widget(widget, stretch=0)
      
      Add widget to right side (moves between rows).
      
      :param widget: Widget to add
      :param stretch: Stretch factor for layout

ResponsiveParameterRow
~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: ResponsiveParameterRow(width_threshold=350, parent=None, layout_config=None)
   
   Specialized responsive row for parameter forms.
   
   :param width_threshold: Minimum width before wrapping triggers (default: 350)
   
   .. py:method:: set_label(widget)
      
      Set the label widget with word wrap enabled.
      
   .. py:method:: set_input(widget)
      
      Set the input widget with expanding size policy.
      
   .. py:method:: set_reset_button(widget)
      
      Set the reset button widget.
      
   .. py:method:: set_help_button(widget)
      
      Set the help button widget.

ResponsiveGroupBoxTitle
~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: ResponsiveGroupBoxTitle(parent=None, width_threshold=300)
   
   Responsive title widget for GroupBoxWithHelp.
   
   :param width_threshold: Minimum width before wrapping triggers (default: 300)
   
   .. py:method:: set_title_widget(widget)
      
      Set the title label widget.
      
   .. py:method:: set_help_widget(widget)
      
      Set the help button widget.
      
   .. py:method:: add_right_widget(widget, stretch=0)
      
      Add right-aligned widget that moves to row 2 when wrapping.
      
   .. py:method:: add_inline_widget(widget, stretch=0)
      
      Add inline widget that stays with title in row 1.

Utility Functions
~~~~~~~~~~~~~~~~~

.. py:function:: set_wrapping_enabled(enabled: bool)
   
   Globally enable or disable responsive wrapping.
   
   :param enabled: True to enable wrapping, False to disable

.. py:function:: is_wrapping_enabled() -> bool
   
   Check if responsive wrapping is globally enabled.
   
   :returns: True if wrapping is enabled, False otherwise

Best Practices
--------------

Width Threshold Selection
~~~~~~~~~~~~~~~~~~~~~~~~~

Choose appropriate width thresholds based on expected content:

- **Parameter rows**: 150-200px (labels + input + reset button)
- **GroupBox titles**: 250-350px (title + help + control buttons)
- **Dialog headers**: 300-400px (title bar + action buttons)

Content Considerations
~~~~~~~~~~~~~~~~~~~~~~

1. **Label text**: Enable word wrap for long labels
2. **Widget sizing**: Use Expanding policy for inputs, Preferred for labels
3. **Button placement**: Right-aligned buttons should have minimal stretch
4. **Minimum sizes**: Set reasonable minimum sizes to prevent over-compression

Performance
~~~~~~~~~~~

The responsive system is optimized for performance:

- Layout calculations use debounced resize events (100ms delay)
- Font metrics are calculated once per widget
- No continuous polling - only recalculates on resize
- Minimal widget reparenting - only when switching modes
