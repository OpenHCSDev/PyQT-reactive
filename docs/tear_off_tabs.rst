Tear-Off Tabs
=============

Tear-off tabs provide Chrome-style detachable tab functionality, allowing users to drag tabs out to create floating windows and dock them into other windows.

Overview
--------

The tear-off tab system enables a flexible multi-window workflow where users can:

- Drag tabs out to create independent floating windows
- Drag floating windows into other tab widgets to dock them
- Organize workspace by distributing tabs across multiple windows
- Restore tabs to their original location

Key Features
~~~~~~~~~~~~

- **Chrome-style interaction**: Drag tabs out vertically or horizontally to tear off
- **Cross-window docking**: Drop tabs into any other TearOffTabWidget
- **Visual feedback**: Drop indicator shows where tab will be inserted
- **Automatic cleanup**: Empty floating windows close automatically
- **Window dragging**: Move floating windows by dragging anywhere in the window
- **Persistent content**: Widget state is preserved during tear-off/dock operations

Architecture
------------

The tear-off tab system consists of four main components:

TearOffTabBar
~~~~~~~~~~~~~

Custom tab bar that detects tear-off gestures:

- Tracks mouse press position for drag start
- Detects drag distance exceeding threshold (30 pixels)
- Detects drag outside tab bar bounds
- Emits tear-off request with tab index and position

TearOffTabWidget
~~~~~~~~~~~~~~~~

Main tab widget with tear-off and drop support:

- Uses TearOffTabBar for tab bar
- Accepts drops from other TearOffTabWidgets
- Manages floating window lifecycle
- Shows visual drop indicators
- Emits signals for tear-off and dock events

TearOffRegistry
~~~~~~~~~~~~~~~

Global singleton registry for cross-window coordination:

- Tracks current drag operation
- Registers all tear-off capable widgets
- Manages drop target detection
- Coordinates drag hover state

FloatingTabWindow
~~~~~~~~~~~~~~~~~

Floating window containing torn-off tab content:

- Contains single tab's widget
- Draggable by mouse
- Detects hover over drop targets
- Handles dock on release
- Restores tab to source if closed without docking

Usage
-----

Basic Tear-Off Tabs
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
   from pyqt_reactive.widgets.shared.tear_off_tab_widget import TearOffTabWidget
   
   app = QApplication([])
   
   # Create tab widget with tear-off support
   tabs = TearOffTabWidget()
   
   # Add tabs
   tab1 = QWidget()
   layout1 = QVBoxLayout(tab1)
   layout1.addWidget(QLabel("Content for Tab 1"))
   tabs.addTab(tab1, "Tab 1")
   
   tab2 = QWidget()
   layout2 = QVBoxLayout(tab2)
   layout2.addWidget(QLabel("Content for Tab 2"))
   tabs.addTab(tab2, "Tab 2")
   
   # Show
   tabs.show()
   app.exec()

With Event Callbacks
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   tabs = TearOffTabWidget()
   
   # Set callback for tab tear-off
   tabs.on_tab_torn_off = lambda widget, text: print(f"Torn off: {text}")
   
   # Set callback for tab dock
   tabs.on_tab_docked = lambda widget, text, index: print(f"Docked: {text} at {index}")
   
   # Or connect to signals
   tabs.tab_torn_off.connect(on_tear_off)
   tabs.tab_docked.connect(on_dock)

TabbedFormWidget Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

TearOffTabWidget is used automatically by TabbedFormWidget:

.. code-block:: python

   from pyqt_reactive.widgets.shared.tabbed_form_widget import TabbedFormWidget, TabbedFormConfig
   
   config = TabbedFormConfig(
       form_field_configs=[...],
       color_scheme=color_scheme
   )
   
   tabbed = TabbedFormWidget(config=config)
   # Tabs can be torn off and docked elsewhere

Cross-Window Workflow
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # Window 1
   window1_tabs = TearOffTabWidget()
   window1_tabs.addTab(content_a, "Tab A")
   window1_tabs.addTab(content_b, "Tab B")
   window1_tabs.show()
   
   # Window 2
   window2_tabs = TearOffTabWidget()
   window2_tabs.addTab(content_c, "Tab C")
   window2_tabs.show()
   
   # User can drag Tab A from window1 to window2
   # Tab A will be removed from window1 and added to window2

API Reference
-------------

TearOffTabWidget
~~~~~~~~~~~~~~~~

.. py:class:: TearOffTabWidget(parent=None)
   
   Tab widget with tear-off and docking support.
   
   .. py:attribute:: on_tab_torn_off
      
      Callback when tab is torn off. Signature: ``(widget, text) -> None``
      
   .. py:attribute:: on_tab_docked
      
      Callback when tab is docked. Signature: ``(widget, text, index) -> None``
      
   .. py:attribute:: tab_torn_off
      
      Signal emitted when tab is torn off. Signature: ``(QWidget, str)``
      
   .. py:attribute:: tab_docked
      
      Signal emitted when tab is docked. Signature: ``(QWidget, str, int)``

TearOffRegistry
~~~~~~~~~~~~~~~

.. py:class:: TearOffRegistry
   
   Singleton registry for cross-window tear-off operations.
   
   .. py:classmethod:: register_drag(drag_data, floating_window)
      
      Register a new drag operation.
      
   .. py:classmethod:: clear_drag()
      
      Clear current drag operation.
      
   .. py:classmethod:: get_current_drag() -> Optional[TabDragData]
      
      Get current drag data.
      
   .. py:classmethod:: register_target(target)
      
      Register widget as potential drop target.
      
   .. py:classmethod:: unregister_target(target)
      
      Unregister drop target.
      
   .. py:classmethod:: check_hover(floating_window, global_pos)
      
      Check if floating window is hovering over drop target.
      
   .. py:classmethod:: perform_drop(floating_window, target)
      
      Perform drop operation.

Best Practices
--------------

Widget Lifecycle
~~~~~~~~~~~~~~~~

Widgets maintain their state during tear-off/dock:

- Widget is not deleted during tear-off
- Widget parent changes from tab widget to floating window
- Widget parent changes from floating window to new tab widget on dock
- All widget state (selection, scroll position, etc.) is preserved

State Management
~~~~~~~~~~~~~~~~

For complex widgets with ObjectState integration:

.. code-block:: python

   # ObjectState is preserved during tear-off
   # Connections remain active
   # Changes continue to work across tear-off/dock cycles

Window Management
~~~~~~~~~~~~~~~~~

- Floating windows are top-level dialogs
- They close automatically when tab is docked
- They restore tab to source if closed without docking
- Multiple floating windows can exist simultaneously

Performance Considerations
~~~~~~~~~~~~~~~~~~~~~~~~~~

- Drop target detection happens continuously during drag
- Visual feedback is lightweight (QFrame indicator)
- No expensive operations during drag
- Cleanup is automatic and immediate