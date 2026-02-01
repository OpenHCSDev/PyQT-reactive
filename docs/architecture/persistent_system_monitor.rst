Persistent System Monitor
========================

**Background thread-based system monitoring for non-blocking metric collection.**

**Module**: ``pyqt_reactive.services.persistent_system_monitor``

Overview
--------

``PersistentSystemMonitor`` wraps ``SystemMonitorCore`` with background thread management. It runs metric collection in a separate thread, preventing the main thread from blocking during system queries.

This is useful for GUI applications (PyQt6, Tkinter, etc.) where blocking the main thread causes UI freezes.

Architecture
------------

Thread-Based Architecture
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    ┌─────────────────────────────────────────────────────────┐
    │          PersistentSystemMonitor (Main Thread)        │
    │  ┌──────────────────────────────────────────────┐   │
    │  │      SystemMonitorCore (Framework-Agnostic)│   │
    │  │  - CPU/RAM metrics                         │   │
    │  │  - GPU/VRAM metrics (if available)            │   │
    │  └──────────────────────────────────────────────┘   │
    │                                                     │
    │  Background Thread:                                  │
    │  ┌──────────────────────────────────────────────┐   │
    │  │  Collection Loop (runs every N seconds)     │   │
    │  │  1. Collect metrics                       │   │
    │  │  2. Store in history                      │   │
    │  │  3. Emit signal (if configured)          │   │
    │  │  4. Sleep for interval                     │   │
    │  │  5. Repeat                                │   │
    │  └──────────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────────────┘

Usage
-----

Basic Usage
~~~~~~~~~~

.. code-block:: python

    from pyqt_reactive.services.persistent_system_monitor import PersistentSystemMonitor

    # Create persistent monitor
    monitor = PersistentSystemMonitor(
        update_interval=2.0,       # Update every 2 seconds
        history_length=300,         # Keep 300 points (5 minutes)
    )

    # Start background thread
    monitor.start()

    # Get current metrics (thread-safe)
    metrics = monitor.get_current_metrics()
    print(f"CPU: {metrics['cpu_percent']}%")

    # Stop background thread
    monitor.stop()

Update Interval
~~~~~~~~~~~~~~~

Time between metric collection updates:

.. code-block:: python

    # Default: 2.0 seconds
    monitor = PersistentSystemMonitor(update_interval=2.0)

    # Fast updates (0.5 seconds)
    monitor = PersistentSystemMonitor(update_interval=0.5)

    # Slow updates (5.0 seconds)
    monitor = PersistentSystemMonitor(update_interval=5.0)

History Length
~~~~~~~~~~~~~~

Number of data points to keep in rolling history:

.. code-block:: python

    # Default: 300 points
    monitor = PersistentSystemMonitor(history_length=300)

    # Longer history (600 points = 10 minutes at 1-second interval)
    monitor = PersistentSystemMonitor(history_length=600)

Thread Safety
-------------

Thread-Safe Access
~~~~~~~~~~~~~~~~~~

``PersistentSystemMonitor`` provides thread-safe access to metrics:

.. code-block:: python

    # These methods are thread-safe
    metrics = monitor.get_current_metrics()
    cpu_history = monitor.get_cpu_history()
    ram_history = monitor.get_ram_history()

    # Safe to call from any thread
    def background_task():
        while True:
            metrics = monitor.get_current_metrics()  # Thread-safe
            # ... use metrics

Thread-Safe Updates
~~~~~~~~~~~~~~~~~~~

Internal updates are also thread-safe:

.. code-block:: python

    # Background thread updates metrics
    # Internal locking ensures no race conditions
    # No external locking needed

Signals
-------

**metrics_updated** (pyqtSignal)

Emitted when new metrics are collected. Only available in PyQt6 environment.

.. code-block:: python

    monitor.metrics_updated.connect(self.on_metrics_updated)

    def on_metrics_updated(self, metrics):
        cpu = metrics.get('cpu_percent')
        ram = metrics.get('ram_percent')
        # ... update UI

Note: This signal is **not available** in non-PyQt6 environments (CLI, Textual TUI).

Lifecycle Management
-------------------

Start/Stop
~~~~~~~~~~

Start and stop the background thread:

.. code-block:: python

    # Start background thread
    monitor.start()

    # Check if running
    is_running = monitor.is_running()

    # Stop background thread
    monitor.stop()

    # Wait for thread to finish (optional)
    monitor.join()

Restart
~~~~~~~

Restart the monitor with new configuration:

.. code-block:: python

    # Change update interval
    monitor.restart(update_interval=1.0)

    # Change history length
    monitor.restart(history_length=600)

Auto-Start
~~~~~~~~~~~

The monitor does **not** auto-start. You must call ``start()`` explicitly:

.. code-block:: python

    monitor = PersistentSystemMonitor(update_interval=2.0)
    monitor.start()  # Must call this

Performance Considerations
--------------------------

CPU Overhead
~~~~~~~~~~~~~

System monitoring has minimal CPU overhead:

- **psutil**: ~0.1-0.5% CPU per query
- **GPUtil**: ~0.05-0.1% CPU per query (if GPU available)
- **Total**: ~0.15-0.6% CPU at 2-second interval

Memory Overhead
~~~~~~~~~~~~~~

Memory usage depends on history length:

.. code-block:: python

    # Memory per metric: ~24 bytes (float) + overhead
    # 4 metrics * 300 points = ~28.8 KB
    # 4 metrics * 600 points = ~57.6 KB

Thread Contention
~~~~~~~~~~~~~~~~

The background thread sleeps for ``update_interval`` seconds, minimizing contention:

.. code-block:: python

    # Collection loop (simplified)
    while True:
        metrics = collect_metrics()  # Fast (~10-20ms)
        store_metrics(metrics)      # Fast (~1-2ms)
        emit_signal(metrics)       # Fast (~1-2ms if configured)
        time.sleep(update_interval)  # Sleep (2.0 seconds)

Integration with PyQt6
-------------------------

Signal-Based Updates
~~~~~~~~~~~~~~~~~~~

In PyQt6, use the ``metrics_updated`` signal:

.. code-block:: python

    from PyQt6.QtWidgets import QWidget
    from pyqt_reactive.services.persistent_system_monitor import PersistentSystemMonitor

    class MyWidget(QWidget):
        def __init__(self):
            super().__init__()

            # Create monitor
            self.monitor = PersistentSystemMonitor(update_interval=2.0)

            # Connect to signal
            self.monitor.metrics_updated.connect(self.on_metrics_updated)

            # Start
            self.monitor.start()

        def on_metrics_updated(self, metrics):
            # Update UI (runs in main thread)
            cpu = metrics.get('cpu_percent')
            self.cpu_label.setText(f"CPU: {cpu}%")

Integration with Textual TUI
------------------------------

Callback-Based Updates
~~~~~~~~~~~~~~~~~~~~

In Textual TUI, poll the monitor periodically:

.. code-block:: python

    from textual.app import App, Compose
    from pyqt_reactive.services.persistent_system_monitor import PersistentSystemMonitor

    class MonitorApp(App):
        def __init__(self):
            super().__init__()
            self.monitor = PersistentSystemMonitor(update_interval=2.0)
            self.monitor.start()

        def on_timer(self):
            # Poll metrics (no signals in Textual)
            metrics = self.monitor.get_current_metrics()
            self.update_display(metrics)

Integration with SystemMonitorCore
-----------------------------------

``PersistentSystemMonitor`` wraps ``SystemMonitorCore``:

.. code-block:: text

    PersistentSystemMonitor
         │
         ├──> wraps ──> SystemMonitorCore (framework-agnostic)
         │                        │
         │                        ├──> CPU/RAM metrics (psutil)
         │                        └──> GPU/VRAM metrics (GPUtil)
         │
         └──> adds ──> Background thread management

You can access the underlying ``SystemMonitorCore``:

.. code-block:: python

    # Access underlying monitor core
    core = monitor.core

    # Call core methods directly
    metrics = core.collect_metrics()

See Also
--------

- :doc:`system_monitor_core` - Framework-agnostic monitoring core
- :doc:`system_monitor` - PyQt6 system monitor widget
- :doc:`gui_performance_patterns` - Performance optimization patterns
