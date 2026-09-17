Flash Animation System
======================

**Game engine-style O(1) per-window flash animations for UI feedback.**

*Module: pyqt_reactive.animation.flash_mixin*

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

1. **fade_in**: Quick fade-in with OutQuad easing
2. **hold**: Hold at maximum intensity
3. **fade_out**: Slow fade-out with InOutCubic easing

``FlashConfig`` owns the durations, peak opacity, and label-mask padding.
Model-driven flashes come
from ObjectState's resolved-value change notifications: resetting an already
default value does not flash, including an explicit default becoming inherited
without changing its resolved value.
The same notification refreshes visible values. ``WidgetService`` skips equal
assignments using the widget's current value; forms do not maintain a separate
local-edit suppression cache.

Widget-Type-Specific Masking
--------------------------------

Flash animations use widget-type-specific masking strategies for precise visual feedback:

**Masking Strategies**:

- **Checkbox**: Tight mask for indicator + label text using Qt style subelement rects
- **Labels**: Full laid-out label-widget geometry with the small padding
  declared by ``FlashConfig``
- **Other controls**: Full laid-out widget geometry
- **Changed fields**: Complete inputs and individual label/help controls remain clear

Custom controls declare ``FlashMaskRectProvider`` when their painted extent
differs from their native Qt base. ``HelpIndicator`` preserves its complete
styled icon rectangle, even though its Qt base is a label.

**Native Mask Paths**:

``FlashElement.get_child_paths`` supplies window-relative ``QPainterPath``
exclusions. The overlay subtracts these paths without interpreting widget types
or square/rounded flags. ``get_child_mask_path`` derives native control geometry;
``get_child_mask_rect`` projects its bounds for layout and scrolling.

Label masks use their stable widget geometry rather than rasterizing glyphs or
calculating text contours. The padding declared by ``FlashConfig`` keeps the
clear region from touching the label chrome. Input and help controls retain
their complete declared shape.

**Function Pane Title Masking**:

Title owners expose their visible controls through
``flash_title_mask_widgets()``. ``GroupBoxWithHelp`` derives these controls from
its existing title layout, so its label, help button and reset control remain
clear without a second manually maintained list of title components.

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

Context and leaf registration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``register_flash_leaf`` registers one inverse-mask source under the semantic
field key. It paints the surrounding groupbox at the shared ``FlashConfig``
opacity while leaving the title, complete changed input, label text and help
controls clear. Label and responsive-title containers supply their visible
controls rather than a rectangle covering the intervening empty layout space.
When a lazily built field becomes available, its precise source replaces the
temporary container-only source for that field.

``MaskedFlashElement`` derives shared paint ownership from the physical
container. When several fields change together, their independently cached
geometry contributes to one paint layer. The painted paths intersect, retaining
every active field's cutout. The strongest active flash supplies the colour and
opacity; a fading field cannot repaint another active field's clear area.

The registration API remains:

.. code-block:: python

    self.register_flash_leaf(
        key="my_field",
        groupbox=my_groupbox,
        leaf_widget=my_widget,
        label_widget=my_label
    )

Reset and provenance feedback identifies the nested input through its clear
cutout in the surrounding flash.

**Masking Behavior**:

- **STANDARD mode** (``leaf_widget=None``): Mask ALL children, flash only frame/background
- **INVERSE context source** (``leaf_widget=widget``): Mask title + leaf widget + label, flash frame + siblings
- **Concurrent leaf sources**: Share one container paint layer with combined cutouts

Usage with FlashMixin
---------------------

Widgets inherit ``FlashMixin`` (alias: ``VisualUpdateMixin``) to participate:

.. code-block:: python

   from pyqt_reactive.animation.flash_mixin import FlashMixin

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
