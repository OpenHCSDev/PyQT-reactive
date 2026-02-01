Flash Animation System
======================

**Game engine-style O(1) per-window flash animations for UI feedback.**

*Module: openhcs.pyqt_gui.widgets.shared.flash_mixin*

Overview
--------

The flash animation system provides visual feedback when configuration values change.
It uses a game engine architecture to achieve O(1) rendering per window regardless
of how many elements are flashing.

Architecture
------------

The system consists of three core components:

1. **_GlobalFlashCoordinator** (singleton): ONE 60fps timer for ALL windows
2. **WindowFlashOverlay** (per-window): Renders ALL flash rectangles in ONE paintEvent
3. **FlashMixin** (per-widget): API for registering elements and triggering flashes

.. code-block:: text

   ┌─────────────────────────────────────────────────────────────┐
   │                  _GlobalFlashCoordinator                    │
   │  ┌─────────────────┐  ┌──────────────────────────────────┐  │
   │  │ _flash_start_   │  │ _computed_colors: Dict[key, QColor] │
   │  │   times: Dict   │  │ (pre-computed each tick)          │  │
   │  └─────────────────┘  └──────────────────────────────────┘  │
   │                              │                              │
   │                              ▼                              │
   │                    [60fps timer tick]                       │
   │                              │                              │
   └──────────────────────────────┼──────────────────────────────┘
                                  │
           ┌──────────────────────┼──────────────────────┐
           ▼                      ▼                      ▼
   ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
   │WindowFlashOverlay│   │WindowFlashOverlay│   │WindowFlashOverlay│
   │   (Window A)  │      │   (Window B)  │      │   (Window C)  │
   │               │      │               │      │               │
   │ ONE paintEvent│      │ ONE paintEvent│      │ ONE paintEvent│
   │ renders ALL   │      │ renders ALL   │      │ renders ALL   │
   │ flash rects   │      │ flash rects   │      │ flash rects   │
   └───────────────┘      └───────────────┘      └───────────────┘

Performance Model
-----------------

**Before (O(n) per tick):**

.. code-block:: text

   Timer tick → compute N colors → store in dict → N widget repaints

**After (O(1) per window):**

.. code-block:: text

   Timer tick → compute colors once → prune expired → ONE overlay.update() per window

Each ``WindowFlashOverlay.paintEvent()`` renders all flash rectangles for its window
in a single paint call. Geometry is cached and only recomputed on scroll/resize.

Animation Phases
----------------

Flash animations have three phases with configurable durations:

1. **fade_in** (100ms): Quick fade-in with OutQuad easing
2. **hold** (50ms): Hold at maximum intensity
3. **fade_out** (350ms): Slow fade-out with InOutCubic easing

Widget-Type-Specific Masking
--------------------------------

Flash animations use widget-type-specific masking strategies for precise visual feedback:

**Masking Strategies**:

- **Checkbox**: Tight mask for indicator + label text using Qt style subelement rects
- **Label**: Tight mask using ``sizeHint()`` to avoid empty layout space
- **Help Button**: Fixed square mask when ``_square_size`` is set
- **All other widgets**: Full rectangle mask

**Checkbox Square Cutout**:

Textless checkboxes (no label) use square cutouts to avoid rounding:

.. code-block:: python

    def _needs_square_checkbox_mask(widget: QWidget) -> bool:
        return isinstance(widget, QCheckBox) and not widget.text()

**Function Pane Title Masking**:

Function panes mask title row widgets tightly:

.. code-block:: python

    def _get_function_pane_title_widgets(groupbox: QWidget) -> List[QWidget]:
        pane = groupbox
        while pane is not None:
            if hasattr(pane, "_flash_title_container") or hasattr(pane, "_module_path_label"):
                break
            pane = pane.parentWidget()

        widgets = []
        module_label = getattr(pane, "_module_path_label", None)
        if module_label and module_label.isVisible():
            widgets.append(module_label)

        title_container = getattr(pane, "_flash_title_container", None)
        if title_container and title_container.isVisible():
            for child in title_container.findChildren(QWidget):
                if child.isVisible() and isinstance(child, LEAF_WIDGET_TYPES):
                    widgets.append(child)

        return widgets

FlashElement Types
------------------

The system supports multiple element types via ``FlashElement`` dataclass:

.. list-table::
   :header-rows: 1

   * - Element Type
     - Factory Function
     - Use Case
   * - Groupbox
     - ``create_groupbox_element()``
     - Form section headers (STANDARD mode masks all children, INVERSE mode masks title + leaf_widget)
   * - Groupbox (full rect)
     - ``create_groupbox_element(..., use_full_rect=True)``
     - Flash entire groupbox geometry (no margin-top offset)
   * - Tree Item
     - ``create_tree_item_element()``
     - Config hierarchy trees
   * - List Item
     - ``create_list_item_element()``
     - Step/function lists

INVERSE Mode with Label Widget Masking
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

INVERSE mode now masks title + leaf_widget + label_widget (not all title row widgets):

.. code-block:: python

    self.register_flash_leaf(
        key="my_field",
        groupbox=my_groupbox,
        leaf_widget=my_widget,
        label_widget=my_label  # NEW: mask label too
    )

This highlights "all fields that inherited the change" while keeping the changed field and its label visible.

**Masking Behavior**:

- **STANDARD mode** (``leaf_widget=None``): Mask ALL children, flash only frame/background
- **INVERSE mode** (``leaf_widget=widget``): Mask title + leaf_widget + label_widget, flash frame + all siblings

Usage with FlashMixin
---------------------

Widgets inherit ``FlashMixin`` (alias: ``VisualUpdateMixin``) to participate:

.. code-block:: python

   from openhcs.pyqt_gui.widgets.shared.flash_mixin import FlashMixin

   class MyWidget(QWidget, FlashMixin):
       def __init__(self):
           super().__init__()
           self._init_flash_mixin()

       def setup_flash(self, groupbox: QGroupBox):
           # Register element for flashing
           self.register_flash_groupbox("my_key", groupbox)

       def trigger_flash(self):
           # Trigger flash (global - all windows with this key)
           self.queue_flash("my_key")

           # Or local flash (this window only)
           self.queue_flash_local("my_key")

Scope-Based Flash Keys
----------------------

Flash keys are automatically scoped to prevent cross-window contamination:

.. code-block:: python

   # Key "well_filter" becomes "orchestrator::plate_1::well_filter"
   scoped_key = self._get_scoped_flash_key("well_filter")

This ensures flashing ``step_0`` in plate1 window doesn't flash ``step_0`` in plate2.

OpenGL Acceleration
-------------------

On systems with OpenGL 3.3+, the system uses ``WindowFlashOverlayGL`` for GPU-accelerated
rendering via instanced draw calls. Falls back to QPainter automatically.

See Also
--------

- :doc:`flash_callback_system` - How ObjectState triggers flash callbacks
- :doc:`gui_performance_patterns` - Cross-window preview system
- :doc:`abstract_manager_widget` - AbstractManagerWidget uses FlashMixin

