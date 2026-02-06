Log Viewer System
==================

**Log file viewer with real-time streaming and syntax highlighting.**

**Module**: ``pyqt_reactive.widgets.log_viewer``

Overview
--------

The log viewer system provides real-time log file viewing with syntax highlighting for timestamps, log levels, logger names, file paths, Python strings, and numbers.

It uses a multi-process architecture:

1. **LogStreamer** (subprocess): Streams log lines as JSONL chunks
2. **LogHighlighter** (subprocess): Highlights log lines via JSONL
3. **LogLoader** (subprocess): Loads log files efficiently
4. **LogHighlightClient** (client): Coordinates subprocess communication
5. **LogViewerWidget** (PyQt6): Renders highlighted logs

This subprocess architecture prevents the main GUI thread from blocking during log parsing.

Architecture
------------

Multi-Process Design
~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    ┌─────────────────────────────────────────────────────────┐
    │              LogViewerWidget (Main Thread)           │
    │  ┌──────────────────────────────────────────────┐   │
    │  │       LogHighlightClient (Subprocess Client)   │   │
    │  │         (JSONL I/O via stdin/stdout)         │   │
    │  └──────────────────────────────────────────────┘   │
    │                                                     │
    │  Subprocesses:                                     │
    │  ┌──────────────────────────────────────────────┐   │
    │  │        LogStreamer (Streaming)               │   │
    │  │  - Tail log file                          │   │
    │  │  - Emit lines as JSONL                    │   │
    │  └──────────────────────────────────────────────┘   │
    │                                                     │
    │  ┌──────────────────────────────────────────────┐   │
    │  │        LogHighlighter (Highlighting)          │   │
    │  │  - Parse log lines                         │   │
    │  │  - Apply syntax highlighting               │   │
    │  │  - Emit segments as JSONL                 │   │
    │  └──────────────────────────────────────────────┘   │
    │                                                     │
    │  ┌──────────────────────────────────────────────┐   │
    │  │        LogLoader (Loading)                   │   │
    │  │  - Load log file efficiently               │   │
    │  │  - Handle UTF-8 errors                   │   │
    │  └──────────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────────────┘

JSONL Protocol
~~~~~~~~~~~~~~~

All subprocesses use JSON Lines (JSONL) for efficient I/O:

.. code-block:: python

    # LogStreamer output
    {"line": "2026-02-01 00:25:57,633 - pyqt_reactive.widgets - INFO - Starting..."}

    # LogHighlighter output
    {
        "line": "2026-02-01 00:25:57,633 - pyqt_reactive.widgets - INFO - Starting...",
        "segments": [
            {"start": 0, "length": 23, "color": [105, 105, 105]},
            {"start": 24, "length": 4, "color": [100, 160, 210], "bold": true},
            {"start": 30, "length": 16, "color": [147, 112, 219]},
            ...
        ]
    }

Syntax Highlighting
-----------------

Log Highlighter
~~~~~~~~~~~~~~

``LogHighlighter`` parses log lines and applies highlighting for:

**Timestamps** (gray):

.. code-block:: text

    2026-02-01 00:25:57,633  ← Gray (105, 105, 105)

**Log Levels** (color + bold):

.. code-block:: text

    CRITICAL  ← Red (255, 85, 85), bold
    ERROR     ← Red (255, 85, 85), bold
    WARNING   ← Orange (255, 140, 0), bold
    INFO      ← Blue (100, 160, 210), bold
    DEBUG     ← Blue (100, 160, 210), bold

**Logger Names** (purple):

.. code-block:: text

    pyqt_reactive.widgets  ← Purple (147, 112, 219)

**File Paths** (green):

.. code-block:: text

    /home/ts/code/projects/pyqt-reactive/src/pyqt_reactive/widgets/__init__.py  ← Green (34, 139, 34)

**Python Strings** (brown):

.. code-block:: text

    "Starting pyqt-reactive PyQt6 GUI..."  ← Brown (206, 145, 120)

**Numbers** (light gray-green):

.. code-block:: text

    123, 45.67, 0xFF  ← Light gray-green (181, 206, 168)

Usage
-----

Basic Usage
~~~~~~~~~~

.. code-block:: python

    from pyqt_reactive.widgets.log_viewer import LogViewerWidget
    from pathlib import Path

    # Create log viewer
    log_path = Path("/home/ts/.local/share/pyqt-reactive/logs/pyqt_reactive_unified.log")
    viewer = LogViewerWidget(log_path=log_path)

    # Add to layout
    layout.addWidget(viewer)

Log Streaming
~~~~~~~~~~~~~~

The log viewer can stream new log lines in real-time:

.. code-block:: python

    # Enable streaming
    viewer.start_streaming()

    # Stop streaming
    viewer.stop_streaming()

    # Check if streaming
    is_streaming = viewer.is_streaming()

Log Highlighting
~~~~~~~~~~~~~~~~

Highlighting is applied automatically via the subprocess:

.. code-block:: python

    # Highlighting is automatic - no configuration needed
    # The viewer receives highlighted segments via JSONL

Manual Highlighting
~~~~~~~~~~~~~~~~~~

You can manually highlight log lines:

.. code-block:: python

    from pyqt_reactive.utils.log_highlight_client import LogHighlightClient

    # Highlight a single line
    client = LogHighlightClient()
    segments = client.highlight_line(
        "2026-02-01 00:25:57,633 - pyqt_reactive.widgets - INFO - Starting..."
    )

    # segments contains highlighting info
    # [{"start": 0, "length": 23, "color": [105, 105, 105]}, ...]

Log Loading
~~~~~~~~~~

Load an entire log file efficiently:

.. code-block:: python

    from pyqt_reactive.utils.log_loader import load_log_file

    # Load log file
    log_path = Path("/path/to/log.log")
    content = load_log_file(log_path)

    # Handle UTF-8 errors gracefully
    content = load_log_file(log_path, errors="replace")

Configuration
-------------

Max Lines
~~~~~~~~~~

Maximum number of lines to display in the viewer:

.. code-block:: python

    # Default: 10,000 lines
    viewer = LogViewerWidget(
        log_path=log_path,
        max_lines=10000
    )

Line Wrapping
~~~~~~~~~~~~~~

Enable/disable line wrapping:

.. code-block:: python

    # Enable line wrapping (default)
    viewer.set_line_wrapping(True)

    # Disable line wrapping (horizontal scrollbar)
    viewer.set_line_wrapping(False)

Filtering
~~~~~~~~~~

Filter log lines by log level:

.. code-block:: python

    # Show only ERROR and CRITICAL
    viewer.set_log_level_filter(["ERROR", "CRITICAL"])

    # Show all levels
    viewer.set_log_level_filter(None)

Performance Considerations
--------------------------

Subprocess Architecture
~~~~~~~~~~~~~~~~~~~~~~

Using subprocesses prevents the main GUI thread from blocking:

.. code-block:: python

    # LogHighlighter runs in separate process
    # Does not block GUI during parsing
    segments = client.highlight_line(line)  # Non-blocking

JSONL Efficiency
~~~~~~~~~~~~~~~~~

JSON Lines (JSONL) is more efficient than full JSON arrays:

.. code-block:: python

    # JSON Lines (efficient)
    {"line": "..."}  # One JSON object per line

    # JSON Array (inefficient)
    [{"line": "..."}, {"line": "..."}]  # Full array parsing needed

Lazy Line Rendering
~~~~~~~~~~~~~~~~~~~

The viewer renders lines lazily for performance:

.. code-block:: python

    # Only visible lines are rendered
    # Invisible lines are not processed
    viewer.update_visible_lines()

Integration with Other Components
----------------------------------

System Monitor Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~

The log viewer can be opened from the system monitor:

.. code-block:: python

    from pyqt_reactive.widgets.system_monitor import SystemMonitorWidget
    from pyqt_reactive.widgets.log_viewer import LogViewerWidget

    # Create monitor
    monitor = SystemMonitorWidget()

    # Connect to log viewer signal
    monitor.show_log_viewer.connect(self.show_log_viewer)

    def show_log_viewer(self):
        log_path = Path("/path/to/log.log")
        viewer = LogViewerWidget(log_path=log_path)
        viewer.show()

Subprocess Utilities
--------------------

LogStreamer
~~~~~~~~~~

Stream log file lines as JSONL chunks:

.. code-block:: python

    from pyqt_reactive.utils.log_streamer import tail_lines

    # Tail last N lines
    lines = tail_lines(Path("/path/to/log.log"), max_lines=100)

    # Stream continuously
    for line in stream_lines(Path("/path/to/log.log")):
        print(line)

LogLoader
~~~~~~~~~~

Load log file efficiently:

.. code-block:: python

    from pyqt_reactive.utils.log_loader import main as log_loader

    # Load via subprocess
    import subprocess
    proc = subprocess.Popen(
        ["python", "-m", "pyqt_reactive.utils.log_loader", "/path/to/log.log"],
        stdout=subprocess.PIPE
    )
    content = proc.stdout.read()

LogHighlighter
~~~~~~~~~~~~~~

Highlight log lines via subprocess:

.. code-block:: python

    import subprocess
    import json

    # Highlight a line
    proc = subprocess.Popen(
        ["python", "-m", "pyqt_reactive.utils.log_highlighter"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE
    )

    line = "2026-02-01 00:25:57,633 - pyqt_reactive.widgets - INFO - Starting..."
    proc.stdin.write((line + "\n").encode())
    proc.stdin.close()

    # Get highlighted segments
    result = json.loads(proc.stdout.read().decode())
    segments = result["segments"]

See Also
--------

- :doc:`system_monitor` - System monitor widget
- :doc:`gui_performance_patterns` - Performance optimization patterns
