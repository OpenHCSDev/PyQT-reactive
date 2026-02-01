PyQt6 System Monitor
====================

**Real-time system monitoring with CPU, RAM, GPU, and VRAM usage graphs.**

**Module**: ``pyqt_reactive.widgets.system_monitor``

Overview
--------

``SystemMonitorWidget`` provides real-time system monitoring for PyQt6 applications. It displays graphs for CPU, RAM, GPU, and VRAM usage, migrated from the Textual TUI version with full feature parity.

The widget uses a two-layer architecture:

1. **SystemMonitorCore** (framework-agnostic): Handles metric collection
2. **PersistentSystemMonitor** (background thread): Non-blocking metrics collection
3. **SystemMonitorWidget** (PyQt6): Renders graphs and UI

This separation allows the monitoring core to be reused in both Textual TUI and PyQt6 applications.

Architecture
------------

Component Layers
~~~~~~~~~~~~~~~~

.. code-block:: text

    ┌─────────────────────────────────────────────────────────┐
    │          SystemMonitorWidget (PyQt6)               │
    │  ┌──────────────────────────────────────────────┐   │
    │  │   SystemMonitorCore (Framework-Agnostic)   │   │
    │  │  ┌──────────────────────────────────────┐  │   │
    │  │  │ PersistentSystemMonitor (Thread)     │  │   │
    │  │  │ - CPU metrics                     │  │   │
    │  │  │ - RAM metrics                     │  │   │
    │  │  │ - GPU/VRAM metrics (if available)  │  │   │
    │  │  └──────────────────────────────────────┘  │   │
    │  └──────────────────────────────────────────────┘   │
    │                                                     │
    │  UI:                                                │
    │  - Real-time graphs (PyQtGraph)                      │
    │  - Current value labels                                │
    │  - Action buttons (ButtonPanel)                         │
    │  - Layout toggle (stacked vs side-by-side)             │
    └─────────────────────────────────────────────────────────┘

Lazy PyQtGraph Import
~~~~~~~~~~~~~~~~~~~~~

PyQtGraph imports cupy at module level, which takes 8+ seconds and blocks GUI startup. ``SystemMonitorWidget`` uses lazy loading:

.. code-block:: python

    # Import is delayed until graph creation
    PYQTGRAPH_AVAILABLE = None  # None = not checked
    pg = None  # Will be set when pyqtgraph is imported

    def create_pyqtgraph_section(self):
        """Create graphs - loads pyqtgraph lazily."""
        global PYQTGRAPH_AVAILABLE, pg

        if PYQTGRAPH_AVAILABLE is None:
            try:
                import pyqtgraph as pg  # Lazy import
                PYQTGRAPH_AVAILABLE = True
            except ImportError:
                PYQTGRAPH_AVAILABLE = False

        if PYQTGRAPH_AVAILABLE:
            # Create graphs using pg module
            self.cpu_plot = pg.PlotWidget()
            # ...

Usage
-----

Basic Usage
~~~~~~~~~~~

.. code-block:: python

    from pyqt_reactive.widgets.system_monitor import SystemMonitorWidget
    from pyqt_reactive.theming import ColorScheme

    # Create widget
    color_scheme = ColorScheme()
    monitor = SystemMonitorWidget(
        color_scheme=color_scheme,
        config=None,  # Optional: use default config
    )

    # Add to layout
    layout.addWidget(monitor)

Button Actions
~~~~~~~~~~~~~~~

``SystemMonitor`` uses ``ButtonPanel`` with declarative configuration:

.. code-block:: python

    BUTTON_CONFIGS = [
        ("Global Config", "global_config", "Open global configuration editor"),
        ("Log Viewer", "log_viewer", "Open log viewer window"),
        ("Custom Functions", "custom_functions", "Manage custom functions"),
        ("Test Plate", "test_plate", "Generate synthetic test plate"),
    ]

Each button emits a signal:

.. code-block:: python

    # Connect to button signals
    monitor.show_global_config.connect(self.show_configuration)
    monitor.show_log_viewer.connect(self.show_log_viewer)
    monitor.show_custom_functions.connect(self.manage_custom_functions)
    monitor.show_test_plate_generator.connect(self.show_test_plate_generator)

Signals
-------

**metrics_updated** (pyqtSignal)

Emitted when new metrics are collected:

.. code-block:: python

    monitor.metrics_updated.connect(self.on_metrics_updated)

    def on_metrics_updated(self, metrics):
        cpu = metrics.get('cpu_percent')
        ram = metrics.get('ram_percent')
        # ...

**show_global_config** (pyqtSignal)

Request to show global configuration.

**show_log_viewer** (pyqtSignal)

Request to show log viewer window.

**show_custom_functions** (pyqtSignal)

Request to show custom functions manager.

**show_test_plate_generator** (pyqtSignal)

Request to show synthetic plate generator.

Layout Modes
-------------

``SystemMonitor`` supports two layout modes:

**Stacked Layout** (default):

.. code-block:: text

    ┌─────────────────────────────────┐
    │   CPU: 45%                    │
    │   ┌─────────────────────────┐   │
    │   │     CPU Graph          │   │
    │   └─────────────────────────┘   │
    │                                 │
    │   RAM: 62%                    │
    │   ┌─────────────────────────┐   │
    │   │     RAM Graph          │   │
    │   └─────────────────────────┘   │
    │                                 │
    │   GPU: 78%  VRAM: 85%         │
    │   ┌─────────────────────────┐   │
    │   │     GPU/VRAM Graph     │   │
    │   └─────────────────────────┘   │
    └─────────────────────────────────┘

**Side-by-Side Layout**:

.. code-block:: text

    ┌─────────────────┬─────────────────┐
    │  CPU: 45%      │  RAM: 62%      │
    │  ┌───────────┐  │  ┌───────────┐  │
    │  │  CPU      │  │  │  RAM      │  │
    │  │  Graph    │  │  │  Graph    │  │
    │  └───────────┘  │  └───────────┘  │
    ├─────────────────┼─────────────────┤
    │  GPU: 78%      │  VRAM: 85%     │
    │  ┌───────────┐  │  ┌───────────┐  │
    │  │  GPU/VRAM │  │  │           │  │
    │  │  Graph    │  │  │           │  │
    │  └───────────┘  │  └───────────┘  │
    └─────────────────┴─────────────────┘

Toggle between layouts:

.. code-block:: python

    monitor.toggle_layout()  # Switch between stacked and side-by-side

Configuration
-------------

Update Interval
~~~~~~~~~~~~~~

Metrics collection interval (in seconds):

.. code-block:: python

    # Default: 2 seconds
    monitor = SystemMonitorWidget(update_interval_seconds=2.0)

    # Faster updates (1 second)
    monitor = SystemMonitorWidget(update_interval_seconds=1.0)

History Length
~~~~~~~~~~~~~~

Number of data points to keep in history:

.. code-block:: python

    # Default: 300 points (5 minutes at 1-second interval)
    monitor = SystemMonitorWidget(history_length=300)

    # Longer history (600 points = 10 minutes)
    monitor = SystemMonitorWidget(history_length=600)

Graph Styling
~~~~~~~~~~~~~~

Graph colors and styles can be customized:

.. code-block:: python

    # Default colors (from ColorScheme)
    CPU_COLOR = (255, 100, 100)    # Red
    RAM_COLOR = (100, 255, 100)    # Green
    GPU_COLOR = (100, 100, 255)    # Blue
    VRAM_COLOR = (255, 255, 100)   # Yellow

GPU Detection
--------------

``SystemMonitor`` automatically detects available GPUs:

.. code-block:: python

    # If GPU is available:
    if monitor.gpu_count > 0:
        # GPU and VRAM graphs will be shown
        gpu_metrics = monitor.current_metrics.get('gpu_percent')
        vram_metrics = monitor.current_metrics.get('vram_percent')

    # If no GPU:
    if monitor.gpu_count == 0:
        # Only CPU and RAM graphs shown
        # GPU/VRAM section hidden

Performance Considerations
--------------------------

PyQtGraph OpenGL Acceleration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On systems with OpenGL 3.3+, PyQtGraph uses OpenGL for rendering:

.. code-block:: python

    # Auto-detected and used if available
    # No configuration needed

Fallback to QPainter
~~~~~~~~~~~~~~~~~~~~~~

If OpenGL is not available, PyQtGraph falls back to QPainter (CPU rendering):

.. code-block:: python

    # Automatic fallback - no code changes needed

Thread-Safe Metrics
~~~~~~~~~~~~~~~~~~~~~

``PersistentSystemMonitor`` runs in a background thread and uses thread-safe data structures:

.. code-block:: python

    # Metrics are collected in background thread
    # Updates are posted to main thread via signals
    monitor.metrics_updated.emit(metrics)

Integration with ServiceRegistry
---------------------------------

``SystemMonitor`` integrates with ``ServiceRegistry`` for widget access:

.. code-block:: python

    from pyqt_reactive.services import ServiceRegistry
    from pyqt_reactive.widgets.system_monitor import SystemMonitorWidget

    # Create and register
    monitor = SystemMonitorWidget()
    # Auto-registers via AutoRegisterServiceMixin (if subclassed)

    # Access anywhere
    from pyqt_reactive.services import ServiceRegistry
    monitor = ServiceRegistry.get(SystemMonitorWidget)

Migration from Textual TUI
-------------------------

Feature Parity
~~~~~~~~~~~~~~~

The PyQt6 version maintains feature parity with the Textual TUI version:

- ✅ CPU monitoring with graph
- ✅ RAM monitoring with graph
- ✅ GPU monitoring (if available)
- ✅ VRAM monitoring (if available)
- ✅ Configurable update interval
- ✅ Configurable history length
- ✅ Multiple layout modes
- ✅ Action buttons

Differences
~~~~~~~~~~

| Feature | Textual TUI | PyQt6 |
|---------|---------------|--------|
| Rendering | Terminal text | PyQtGraph widgets |
| Interactivity | Keyboard-driven | Mouse-clickable |
| Update Mechanism | Timer callback | Background thread |
| Layout | Fixed | Resizable (QSplitter) |

See Also
--------

- :doc:`system_monitor_core` - Framework-agnostic monitoring core
- :doc:`persistent_system_monitor` - Background thread monitor
- :doc:`button_panel` - Button panel component
- :doc:`gui_performance_patterns` - Performance optimization patterns
