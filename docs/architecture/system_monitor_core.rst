System Monitor Core
====================

**Framework-agnostic system monitoring core for CPU, RAM, GPU, and VRAM metrics.**

**Module**: ``pyqt_reactive.services.system_monitor_core``

Overview
--------

``SystemMonitorCore`` provides framework-agnostic system monitoring that can be used in any Python application (Textual TUI, PyQt6, CLI tools, etc.).

It collects metrics for:

- **CPU**: CPU usage percentage
- **RAM**: Memory usage percentage
- **GPU**: GPU usage percentage (if available)
- **VRAM**: GPU memory usage percentage (if available)

Architecture
------------

Framework-Agnostic Design
~~~~~~~~~~~~~~~~~~~~~~~~~~

``SystemMonitorCore`` is intentionally decoupled from any UI framework:

.. code-block:: text

    ┌─────────────────────────────────────────────────────────┐
    │         SystemMonitorCore (Framework-Agnostic)      │
    │  ┌──────────────────────────────────────────────┐   │
    │  │  Metrics Collection (psutil + GPUtil)     │   │
    │  │  - CPU usage                               │   │
    │  │  - RAM usage                               │   │
    │  │  - GPU/VRAM usage (if available)            │   │
    │  └──────────────────────────────────────────────┘   │
    │                                                     │
    │  UI Frameworks (plug into SystemMonitorCore):       │
    │  - Textual TUI (SystemMonitorTextual)           │
    │  - PyQt6 (SystemMonitorWidget)                   │
    │  - CLI tools                                     │
    └─────────────────────────────────────────────────────────┘

This allows the same monitoring logic to be reused across different UI frameworks.

Usage
-----

Basic Usage
~~~~~~~~~~

.. code-block:: python

    from pyqt_reactive.services.system_monitor_core import SystemMonitorCore

    # Create monitor with history length
    monitor = SystemMonitorCore(history_length=300)

    # Collect metrics
    metrics = monitor.collect_metrics()
    print(f"CPU: {metrics['cpu_percent']}%")
    print(f"RAM: {metrics['ram_percent']}%")

    # Get history
    cpu_history = monitor.get_cpu_history()
    ram_history = monitor.get_ram_history()

Metrics Collection
~~~~~~~~~~~~~~~~~~

Metrics are collected using:

- **psutil**: CPU and RAM metrics
- **GPUtil**: GPU and VRAM metrics (if available)

.. code-block:: python

    metrics = {
        'cpu_percent': float,      # CPU usage (0-100)
        'ram_percent': float,      # RAM usage (0-100)
        'gpu_percent': float,      # GPU usage (0-100) or None
        'vram_percent': float,     # VRAM usage (0-100) or None
        'timestamp': float,        # Unix timestamp
    }

GPU Detection
~~~~~~~~~~~~~

``SystemMonitorCore`` automatically detects available GPUs:

.. code-block:: python

    monitor = SystemMonitorCore()

    # Check if GPU is available
    if monitor.gpu_count > 0:
        print(f"Found {monitor.gpu_count} GPU(s)")
        gpu_metrics = monitor.collect_metrics()
        print(f"GPU: {gpu_metrics['gpu_percent']}%")
    else:
        print("No GPU detected")

History Management
-----------------

History Length
~~~~~~~~~~~~~~

The monitor maintains a rolling history of metrics:

.. code-block:: python

    # Create monitor with 300-point history (5 minutes at 1-second interval)
    monitor = SystemMonitorCore(history_length=300)

    # Get current history length
    current_length = len(monitor.cpu_history)  # Will be ≤ 300

Access History
~~~~~~~~~~~~~~

Access individual metric histories:

.. code-block:: python

    # CPU history (list of floats)
    cpu_history = monitor.get_cpu_history()

    # RAM history (list of floats)
    ram_history = monitor.get_ram_history()

    # GPU history (list of floats, or None if no GPU)
    gpu_history = monitor.get_gpu_history()

    # VRAM history (list of floats, or None if no GPU)
    vram_history = monitor.get_vram_history()

Current Metrics
~~~~~~~~~~~~~~

Get the most recent metrics:

.. code-block:: python

    metrics = monitor.get_current_metrics()
    print(f"CPU: {metrics['cpu_percent']}%")
    print(f"RAM: {metrics['ram_percent']}%")

Performance Considerations
--------------------------

psutil vs GPUtil
~~~~~~~~~~~~~~~~~

**psutil** (CPU/RAM):
- Fast, lightweight
- Cross-platform
- Built-in

**GPUtil** (GPU/VRAM):
- Slower, but still fast enough
- GPU-specific
- Optional import (gracefully degrades if not available)

Lazy Import
~~~~~~~~~~~~

GPUtil is imported lazily to avoid blocking:

.. code-block:: python

    # GPUtil imported only when needed
    try:
        import GPUtil
        self._gpus = GPUtil.getGPUs()
    except ImportError:
        self._gpus = []  # Graceful degradation

Thread Safety
-------------

``SystemMonitorCore`` is **not thread-safe** by default. If you need thread-safe access:

.. code-block:: python

    import threading

    class ThreadSafeSystemMonitor:
        def __init__(self):
            self._monitor = SystemMonitorCore()
            self._lock = threading.Lock()

        def collect_metrics(self):
            with self._lock:
                return self._monitor.collect_metrics()

        def update_metrics(self, metrics):
            with self._lock:
                self._monitor.update(metrics)

Integration with Persistent Monitor
-----------------------------------

``PersistentSystemMonitor`` wraps ``SystemMonitorCore`` with background thread management:

.. code-block:: python

    from pyqt_reactive.services.persistent_system_monitor import PersistentSystemMonitor

    # Create persistent monitor
    monitor = PersistentSystemMonitor(
        update_interval=2.0,      # Update every 2 seconds
        history_length=300,        # Keep 300 points
    )

    # Start background thread
    monitor.start()

    # Access metrics (thread-safe)
    metrics = monitor.get_current_metrics()

    # Stop background thread
    monitor.stop()

See Also
--------

- :doc:`system_monitor` - PyQt6 system monitor widget
- :doc:`persistent_system_monitor` - Background thread monitor
- :doc:`gui_performance_patterns` - Performance optimization patterns
