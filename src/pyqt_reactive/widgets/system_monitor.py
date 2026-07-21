"""
System Monitor Widget for PyQt6

Real-time system monitoring with CPU, RAM, GPU, and VRAM usage graphs.
Migrated from Textual TUI with full feature parity.
"""

import logging
import time
from typing import Optional
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout, QSizePolicy, QPushButton, QSplitter
)
from PyQt6.QtCore import QTimer, pyqtSignal, QMetaObject, Qt
from PyQt6.QtGui import QFont, QResizeEvent

# Lazy import of PyQtGraph to avoid blocking startup
# PyQtGraph imports cupy at module level, which takes 8+ seconds
# We'll import it on-demand when creating graphs
PYQTGRAPH_AVAILABLE = None  # None = not checked, True = available, False = not available
pg = None  # Will be set when pyqtgraph is imported

# Import the SystemMonitorCore service (framework-agnostic)
from pyqt_reactive.animation import queue_visual_frame_callback
from pyqt_reactive.theming import StyleSheetGenerator
from pyqt_reactive.theming import ColorScheme

from pyqt_reactive.services.system_monitor_core import SystemMonitorCore
from pyqt_reactive.services.persistent_system_monitor import PersistentSystemMonitor
from pyqt_reactive.services.system_monitor_config import PerformanceMonitorConfig

logger = logging.getLogger(__name__)


class SystemMonitorWidget(QWidget):
    """
    PyQt6 System Monitor Widget.
    
    Displays real-time system metrics with graphs for CPU, RAM, GPU, and VRAM usage.
    Provides the same functionality as the Textual SystemMonitorTextual widget.
    """
    
    # Declarative button configuration (matches AbstractManagerWidget pattern)
    BUTTON_CONFIGS = [
        ("Global Config", "global_config", "Open global configuration editor"),
        ("Log Viewer", "log_viewer", "Open log viewer window"),
        ("Custom Functions", "custom_functions", "Manage custom functions"),
        ("Test Plate", "test_plate", "Generate synthetic test plate"),
    ]
    BUTTON_GRID_COLUMNS = 0  # Single row (all buttons next to each other)
    
    # Signals
    metrics_updated = pyqtSignal(dict)  # Emitted when metrics are updated
    _pyqtgraph_loaded = pyqtSignal()  # Internal signal for async pyqtgraph loading
    _pyqtgraph_failed = pyqtSignal()  # Internal signal for async pyqtgraph loading failure
    
    # Button action signals
    show_global_config = pyqtSignal()  # Request to show global config
    show_log_viewer = pyqtSignal()  # Request to show log viewer
    show_custom_functions = pyqtSignal()  # Request to show custom functions manager
    show_test_plate_generator = pyqtSignal()  # Request to show synthetic plate generator
    
    def __init__(self,
                 color_scheme: Optional[ColorScheme] = None,
                 config: Optional[PerformanceMonitorConfig] = None,
                 parent=None):
        """
        Initialize the system monitor widget.

        Args:
            color_scheme: Color scheme for styling (optional, uses default if None)
            config: System monitor configuration (optional, uses default if None)
            parent: Parent widget
        """
        super().__init__(parent)

        # Initialize configuration
        self.monitor_config = config or PerformanceMonitorConfig()

        # Initialize color scheme and style generator
        self.color_scheme = color_scheme or ColorScheme()
        self.style_generator = StyleSheetGenerator(self.color_scheme)

        # Calculate monitoring parameters from configuration
        update_interval = self.monitor_config.update_interval_seconds
        history_length = self.monitor_config.calculated_max_data_points

        # Core monitoring - use persistent thread for non-blocking metrics collection
        sampler_config = self.monitor_config.sampler_config
        self.monitor = SystemMonitorCore(
            history_length=history_length,
            sampler_config=sampler_config,
        )  # Match the dynamic history length

        self.persistent_monitor = PersistentSystemMonitor(
            update_interval=update_interval,
            history_length=history_length,
            sampler_config=sampler_config,
        )
        # No timer needed - the persistent thread handles timing

        # Track graph layout mode (True = side-by-side, False = stacked)
        # MUST be set before setup_ui() since create_pyqtgraph_section() uses it
        self._graphs_side_by_side = True

        # Delay monitoring start until widget is shown (fixes WSL2 hanging)
        self._monitoring_started = False

        # Plot update state. Curves use a fixed relative x-axis and update only
        # when new metric samples arrive.
        self._last_plot_history = None
        self._history_update_interval = None
        self._plot_point_budget = 2000
        self._history_length = 0
        self._history_x = None
        self._history_cpu = None
        self._history_ram = None
        self._history_gpu = None
        self._history_vram = None
        self._gpu_series_visible = False
        self._vram_series_visible = False
        self._plot_opengl_enabled = False

        # Setup UI
        self.setup_ui()
        self.setup_connections()

        # Set size policy to minimum - let surrounding widgets expand into this space
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        # Set minimum size for usability - more vertically compact
        self.setMinimumSize(200, 160)

        logger.debug("System monitor widget initialized")

    def create_loading_placeholder(self) -> QWidget:
        """
        Create a simple loading placeholder shown while PyQtGraph loads.

        Returns:
            Simple loading label widget
        """
        from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
        from PyQt6.QtCore import Qt

        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)

        label = QLabel("Loading system monitor...")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        return placeholder

    def _load_pyqtgraph_async(self):
        """
        Load PyQtGraph asynchronously using QTimer to avoid blocking.

        We use QTimer instead of threading because Python's GIL causes background
        thread imports to block the main thread anyway. By using QTimer with a delay,
        we give the user time to interact with the UI before the import happens.
        """
        # Load immediately - no artificial delay
        QTimer.singleShot(0, self._import_pyqtgraph_main_thread)
        logger.info("PyQtGraph loading...")

    def _import_pyqtgraph_main_thread(self):
        """Import PyQtGraph in main thread after delay."""
        global PYQTGRAPH_AVAILABLE, pg

        try:
            logger.info("⏳ Loading PyQtGraph (UI will freeze for ~8 seconds)...")
            logger.info("📦 Importing pyqtgraph module...")
            import pyqtgraph as pg_module
            logger.info("📦 PyQtGraph module imported")

            logger.info("🔧 Initializing PyQtGraph (loading GPU libraries: cupy, numpy, etc.)...")
            pg = pg_module
            PYQTGRAPH_AVAILABLE = True
            logger.info("✅ PyQtGraph loaded successfully (GPU libraries ready)")

            # Flush logs so startup screen can read them
            import logging as _logging
            for _h in _logging.getLogger().handlers:
                try:
                    _h.flush()
                except Exception:
                    pass

            # Schedule UI switch on next event loop tick so startup screen can update
            from PyQt6.QtCore import QTimer as _QTimer
            _QTimer.singleShot(0, self._switch_to_pyqtgraph_ui)
        except ImportError as e:
            logger.warning(f"❌ PyQtGraph not available: {e}")
            PYQTGRAPH_AVAILABLE = False

            # Schedule fallback switch similarly
            from PyQt6.QtCore import QTimer as _QTimer
            _QTimer.singleShot(0, self._switch_to_fallback_ui)

    def _switch_to_pyqtgraph_ui(self):
        """Switch from loading placeholder to PyQtGraph UI (called in main thread)."""
        # Remove loading placeholder from graphs container
        old_widget = self.monitoring_widget
        self.graphs_layout.removeWidget(old_widget)
        old_widget.deleteLater()

        # Create PyQtGraph section
        self.monitoring_widget = self.create_pyqtgraph_section()
        # Add to graphs container layout
        self.graphs_layout.addWidget(self.monitoring_widget)

        logger.info("Switched to PyQtGraph UI")

    def _switch_to_fallback_ui(self):
        """Switch from loading placeholder to fallback UI (called in main thread)."""
        # Remove loading placeholder from graphs container
        old_widget = self.monitoring_widget
        self.graphs_layout.removeWidget(old_widget)
        old_widget.deleteLater()

        # Create fallback section
        self.monitoring_widget = self.create_fallback_section()
        # Add to graphs container layout
        self.graphs_layout.addWidget(self.monitoring_widget)

        logger.info("Switched to fallback UI (PyQtGraph not available)")

    def showEvent(self, event):
        """Handle widget show event - start monitoring when widget becomes visible."""
        super().showEvent(event)
        if not self._monitoring_started:
            # Start monitoring only when widget is actually shown
            # This prevents WSL2 hanging issues during initialization
            self.start_monitoring()
            self._monitoring_started = True
            logger.debug("System monitoring started on widget show")

    def resizeEvent(self, event: QResizeEvent):
        """Handle widget resize - adjust font sizes dynamically."""
        super().resizeEvent(event)
        # Defer font size update until after layout is complete
        if hasattr(self, 'info_widget'):
            # Use a timer to update after the layout has settled
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._update_font_sizes_from_panel)

    def closeEvent(self, event):
        """Handle widget close event - cleanup resources."""
        self.cleanup()
        super().closeEvent(event)

    def __del__(self):
        """Destructor - ensure cleanup happens."""
        try:
            self.cleanup()
        except:
            pass  # Ignore errors during destruction

    def _update_font_sizes_from_panel(self):
        """Update font sizes based on the actual info panel width."""
        if not hasattr(self, 'info_widget'):
            return

        # Use the actual info panel width, not the whole widget width
        panel_width = self.info_widget.width()

        # Larger font sizes for better readability
        # Label font: 10-13pt based on panel width
        label_size = max(10, min(13, panel_width // 50))

        # Update all label fonts
        if hasattr(self, 'cpu_cores_label'):
            for label_pair in [
                self.cpu_cores_label, self.cpu_freq_label,
                self.ram_total_label, self.ram_used_label,
                self.gpu_name_label, self.gpu_temp_label, self.vram_label
            ]:
                # Update key label
                key_font = QFont("Arial", label_size)
                label_pair[0].setFont(key_font)

                # Update value label (bold)
                value_font = QFont("Arial", label_size)
                value_font.setBold(True)
                label_pair[1].setFont(value_font)
    
    def setup_ui(self):
        """Setup the user interface with proper splitter hierarchy."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(2)

        # Header (title + status) - similar to AbstractManagerWidget
        header = self._create_header()
        main_layout.addWidget(header)

        # MAIN HSPLIT: Left side (with nested VSPLIT) | Right side (graphs)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # LEFT SIDE: VSPLIT with System Info (top) and Buttons (bottom)
        left_side = self._create_left_side_with_vsplit()
        main_splitter.addWidget(left_side)

        # RIGHT SIDE: Performance Monitor (graphs)
        self.graphs_container = QWidget()
        self.graphs_container.setMinimumSize(1, 1)  # Allow to shrink to minimum
        self.graphs_layout = QVBoxLayout(self.graphs_container)
        self.graphs_layout.setContentsMargins(0, 0, 0, 0)
        self.graphs_layout.setSpacing(0)

        # Start with loading placeholder
        self.monitoring_widget = self.create_loading_placeholder()
        self.graphs_layout.addWidget(self.monitoring_widget)

        main_splitter.addWidget(self.graphs_container)

        # Set sizes: smaller left side, larger graphs area
        main_splitter.setSizes([80, 240])
        main_splitter.setStretchFactor(0, 0)  # Don't expand left side
        main_splitter.setStretchFactor(1, 1)  # Graphs can expand horizontally
        # Cap maximum height for graphs to keep vertical compactness
        self.graphs_container.setMaximumHeight(180)

        main_layout.addWidget(main_splitter)

        # Apply centralized styling
        self.setStyleSheet(self.style_generator.generate_system_monitor_style())

        # Load PyQtGraph asynchronously
        self._load_pyqtgraph_async()

    def _create_header(self) -> QWidget:
        """Create header with title and status label (similar to AbstractManagerWidget)."""
        header = QWidget()
        header.setMinimumHeight(30)  # Ensure title and status are visible
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 5, 5, 5)

        # Title label
        title_label = QLabel("System Monitor")
        title_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title_label.setStyleSheet(
            f"color: {self.color_scheme.to_hex(self.color_scheme.text_accent)};"
        )
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            f"color: {self.color_scheme.to_hex(self.color_scheme.status_success)}; "
            f"font-weight: bold;"
        )
        header_layout.addWidget(self.status_label)

        return header

    def _create_left_side_with_vsplit(self) -> QWidget:
        """Create left side with VSPLIT: System Info on top, buttons on bottom."""
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top: System info panel
        self.info_widget = self.create_info_panel()
        splitter.addWidget(self.info_widget)

        # Bottom: Button panel - store reference for API access
        self.button_panel = self._create_button_panel()
        splitter.addWidget(self.button_panel)

        # Set sizes: fixed sizes - don't expand
        splitter.setSizes([200, 80])
        splitter.setStretchFactor(0, 0)  # Info doesn't expand
        splitter.setStretchFactor(1, 0)  # Buttons don't expand

        return splitter

    def _create_button_panel(self) -> QWidget:
        """Create button panel using reusable ButtonPanel component."""
        from pyqt_reactive.widgets.shared.button_panel import ButtonPanel
        from PyQt6.QtWidgets import QSizePolicy
        
        panel = ButtonPanel(
            button_configs=self.BUTTON_CONFIGS,
            on_action=self.handle_button_action,
            style_generator=self.style_generator,
            grid_columns=self.BUTTON_GRID_COLUMNS,
            parent=self
        )
        # Prevent panel from expanding vertically
        panel.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        return panel
    
    def handle_button_action(self, action_id: str):
        """Handle button actions declaratively."""
        if action_id == "global_config":
            self.show_global_config.emit()
        elif action_id == "log_viewer":
            self.show_log_viewer.emit()
        elif action_id == "custom_functions":
            self.show_custom_functions.emit()
        elif action_id == "test_plate":
            self.show_test_plate_generator.emit()
    
    def _force_refresh(self):
        """Force an immediate refresh of system metrics."""
        logger.debug("Force refresh requested")
        # The persistent monitor updates automatically, but we could add
        # immediate refresh logic here if needed
    
    def create_ascii_widget(self) -> QWidget:
        """Create the ASCII art widget for the bottom."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # ASCII header
        self.header_label = QLabel(self.get_ascii_header())
        self.header_label.setObjectName("header_label")
        font = QFont("Courier", 10)
        font.setBold(True)
        self.header_label.setFont(font)
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.header_label)
        
        return widget

    def create_info_panel(self) -> QWidget:
        """Create a system information panel matching AbstractManagerWidget styling."""
        panel = QWidget()
        panel.setObjectName("info_panel")
        panel.setMinimumSize(1, 1)  # Allow to shrink to minimum

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Two-column grid layout with tighter spacing
        # Grid has 5 columns: [Label1, Value1, Spacer, Label2, Value2]
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(8)
        info_grid.setVerticalSpacing(10)
        info_grid.setColumnStretch(1, 0)  # Left value column - no stretch
        info_grid.setColumnMinimumWidth(2, 15)  # Minimal spacer between columns
        info_grid.setColumnStretch(4, 0)  # Right value column - no stretch

        # Left column - CPU and RAM info (shorter labels)
        self.cpu_cores_label = self.create_info_row("Cores:", "—")
        self.cpu_freq_label = self.create_info_row("Freq:", "—")
        self.ram_total_label = self.create_info_row("RAM:", "—")
        self.ram_used_label = self.create_info_row("Used:", "—")

        info_grid.addWidget(self.cpu_cores_label[0], 0, 0)
        info_grid.addWidget(self.cpu_cores_label[1], 0, 1)
        info_grid.addWidget(self.cpu_freq_label[0], 1, 0)
        info_grid.addWidget(self.cpu_freq_label[1], 1, 1)
        info_grid.addWidget(self.ram_total_label[0], 2, 0)
        info_grid.addWidget(self.ram_total_label[1], 2, 1)
        info_grid.addWidget(self.ram_used_label[0], 3, 0)
        info_grid.addWidget(self.ram_used_label[1], 3, 1)

        # Right column - GPU info (will be hidden if no GPU)
        self.gpu_name_label = self.create_info_row("GPU:", "—")
        self.gpu_temp_label = self.create_info_row("Temp:", "—")
        self.vram_label = self.create_info_row("VRAM:", "—")

        info_grid.addWidget(self.gpu_name_label[0], 0, 3)
        info_grid.addWidget(self.gpu_name_label[1], 0, 4)
        info_grid.addWidget(self.gpu_temp_label[0], 1, 3)
        info_grid.addWidget(self.gpu_temp_label[1], 1, 4)
        info_grid.addWidget(self.vram_label[0], 2, 3)
        info_grid.addWidget(self.vram_label[1], 2, 4)

        layout.addLayout(info_grid)
        # No stretch - panel takes only needed space

        # Schedule initial font size update after panel is shown
        QTimer.singleShot(100, self._update_font_sizes_from_panel)

        return panel

    def create_info_row(self, label_text: str, value_text: str) -> tuple:
        """Create a label-value pair for the info panel (font size set dynamically in resizeEvent)."""
        label = QLabel(label_text)
        label.setObjectName("info_label_key")

        value = QLabel(value_text)
        value.setObjectName("info_label_value")

        return (label, value)
    
    def create_pyqtgraph_section(self) -> QWidget:
        """
        Create PyQtGraph-based monitoring section with consolidated graphs.

        Returns:
            Widget containing consolidated PyQtGraph plots
        """
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(5)

        # Container for graphs that we can re-layout
        self.graph_container = QWidget()
        self.graph_layout = QGridLayout(self.graph_container)
        self.graph_layout.setSpacing(2)  # Minimal spacing between graphs
        self.graph_layout.setContentsMargins(0, 0, 0, 0)  # No margins

        # Configure PyQtGraph based on config settings
        pg.setConfigOption('background', self.color_scheme.to_hex(self.color_scheme.window_bg))
        pg.setConfigOption('foreground', 'white')

        # Create consolidated PyQtGraph plots with minimal size constraints
        self.cpu_gpu_plot = pg.PlotWidget(title="CPU/GPU Usage")
        self.ram_vram_plot = pg.PlotWidget(title="RAM/VRAM Usage")
        self._plot_opengl_enabled = self._configure_plot_acceleration()
        pg.setConfigOption('antialias', self._effective_plot_antialiasing())
        
        # Allow plots to shrink to very small size
        self.cpu_gpu_plot.setMinimumSize(1, 1)
        self.ram_vram_plot.setMinimumSize(1, 1)

        # Disable mouse interaction on plots
        self.cpu_gpu_plot.setMouseEnabled(x=False, y=False)
        self.ram_vram_plot.setMouseEnabled(x=False, y=False)
        self.cpu_gpu_plot.setMenuEnabled(False)
        self.ram_vram_plot.setMenuEnabled(False)

        # Store plot data items for efficient updates using configured colors and line width
        colors = self.monitor_config.chart_colors
        line_width = self.monitor_config.line_width

        # CPU/GPU plot curves
        self.cpu_curve = self.cpu_gpu_plot.plot(pen=pg.mkPen(colors['cpu'], width=line_width), name='CPU')
        self.gpu_curve = self.cpu_gpu_plot.plot(pen=pg.mkPen(colors['gpu'], width=line_width), name='GPU')

        # RAM/VRAM plot curves
        self.ram_curve = self.ram_vram_plot.plot(pen=pg.mkPen(colors['ram'], width=line_width), name='RAM')
        self.vram_curve = self.ram_vram_plot.plot(pen=pg.mkPen(colors['vram'], width=line_width), name='VRAM')
        for curve in (
            self.cpu_curve,
            self.gpu_curve,
            self.ram_curve,
            self.vram_curve,
        ):
            self._configure_plot_curve(curve)

        # Style CPU/GPU plot - minimal padding
        history = float(self.monitor_config.history_duration_seconds)
        self.cpu_gpu_plot.setBackground(self.color_scheme.to_hex(self.color_scheme.panel_bg))
        self.cpu_gpu_plot.setYRange(0, 100)
        self.cpu_gpu_plot.showGrid(x=self.monitor_config.show_grid, y=self.monitor_config.show_grid, alpha=0.3)
        # Disable auto-ranging so manual panning works reliably
        _cpu_vb = self.cpu_gpu_plot.getPlotItem().getViewBox()
        _cpu_vb.setAutoPan(x=False, y=False)
        _cpu_vb.disableAutoRange()

        # Minimize left axis
        self.cpu_gpu_plot.getAxis('left').setTextPen('white')
        self.cpu_gpu_plot.getAxis('left').setStyle(tickLength=-5)
        self.cpu_gpu_plot.getAxis('left').setWidth(35)  # Minimal width for y-axis

        # Hide bottom axis completely
        self.cpu_gpu_plot.getAxis('bottom').setHeight(0)
        self.cpu_gpu_plot.getAxis('bottom').setStyle(showValues=False)

        # Minimize all margins and padding
        self.cpu_gpu_plot.getPlotItem().setContentsMargins(0, 0, 0, 0)
        self.cpu_gpu_plot.getViewBox().setDefaultPadding(0)

        # Style RAM/VRAM plot - minimal padding
        self.ram_vram_plot.setBackground(self.color_scheme.to_hex(self.color_scheme.panel_bg))
        self.ram_vram_plot.setYRange(0, 100)
        self.ram_vram_plot.showGrid(x=self.monitor_config.show_grid, y=self.monitor_config.show_grid, alpha=0.3)
        # Disable auto-ranging so manual panning works reliably
        _ram_vb = self.ram_vram_plot.getPlotItem().getViewBox()
        _ram_vb.setAutoPan(x=False, y=False)
        _ram_vb.disableAutoRange()

        # Minimize left axis
        self.ram_vram_plot.getAxis('left').setTextPen('white')
        self.ram_vram_plot.getAxis('left').setStyle(tickLength=-5)
        self.ram_vram_plot.getAxis('left').setWidth(35)  # Minimal width for y-axis

        # Hide bottom axis completely
        self.ram_vram_plot.getAxis('bottom').setHeight(0)
        self.ram_vram_plot.getAxis('bottom').setStyle(showValues=False)

        # Minimize all margins and padding
        self.ram_vram_plot.getPlotItem().setContentsMargins(0, 0, 0, 0)
        self.ram_vram_plot.getViewBox().setDefaultPadding(0)
        self._apply_fixed_plot_ranges(history)

        # Add plots to grid layout (side-by-side by default)
        self._update_graph_layout()

        # No stretch - let container take minimum size
        main_layout.addWidget(self.graph_container, 0)

        return widget

    def _configure_plot_acceleration(self) -> bool:
        """Enable pyqtgraph's OpenGL curve path for monitor plots when available."""
        if not self.monitor_config.use_opengl:
            pg.setConfigOption('enableExperimental', False)
            self._set_plot_opengl(False)
            return False

        try:
            pg.setConfigOption('enableExperimental', True)
            self._set_plot_opengl(True)
        except Exception as e:
            logger.debug("OpenGL plot acceleration unavailable, falling back to raster plots: %s", e)
            pg.setConfigOption('enableExperimental', False)
            self._set_plot_opengl(False)
            return False
        return True

    def _set_plot_opengl(self, enabled: bool):
        """Switch both monitor plot viewports to the requested rendering backend."""
        self.cpu_gpu_plot.useOpenGL(enabled)
        self.ram_vram_plot.useOpenGL(enabled)

    def _effective_plot_antialiasing(self) -> bool:
        """Use antialiasing on OpenGL plots; avoid expensive raster antialias fallback."""
        if self._plot_opengl_enabled:
            return bool(self.monitor_config.antialiasing)
        return bool(self.monitor_config.antialiasing and not self.monitor_config.use_opengl)

    def _configure_plot_curve(self, curve):
        """Enable cheap pyqtgraph rendering options when the installed version supports them."""
        try:
            curve.setData(antialias=self._effective_plot_antialiasing())
        except Exception:
            pass

        try:
            curve.setClipToView(True)
        except Exception:
            pass

        try:
            curve.setDownsampling(auto=True, method='peak')
        except TypeError:
            try:
                curve.setDownsampling(auto=True, mode='peak')
            except Exception:
                pass
        except Exception:
            pass
    
    def create_layout_toggle_button(self) -> QPushButton:
        """
        Create a toggle button for switching graph layouts.
        This button is meant to be added to the main window's status bar.

        Returns:
            QPushButton configured for layout toggling
        """
        self.layout_toggle_button = QPushButton("⬍ Stack")
        self.layout_toggle_button.setMaximumWidth(80)
        self.layout_toggle_button.setMaximumHeight(24)
        self.layout_toggle_button.setToolTip("Toggle between side-by-side and stacked layout")
        self.layout_toggle_button.clicked.connect(self.toggle_graph_layout)

        # Style the button to match parameter form manager style
        button_styles = self.style_generator.generate_config_button_styles()
        self.layout_toggle_button.setStyleSheet(button_styles["reset"])

        return self.layout_toggle_button

    def toggle_graph_layout(self):
        """Toggle between side-by-side and stacked graph layouts."""
        self._graphs_side_by_side = not self._graphs_side_by_side
        self._update_graph_layout()

        # Update button text via ButtonPanel API
        if hasattr(self, 'button_panel'):
            if self._graphs_side_by_side:
                self.button_panel.set_button_text("toggle_layout", "Stack")
            else:
                self.button_panel.set_button_text("toggle_layout", "Side-by-Side")

    def _update_graph_layout(self):
        """Update the graph layout based on current mode."""
        # Remove all widgets from layout
        while self.graph_layout.count():
            item = self.graph_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        if self._graphs_side_by_side:
            # Side-by-side: 1 row, 2 columns
            self.graph_layout.addWidget(self.cpu_gpu_plot, 0, 0)
            self.graph_layout.addWidget(self.ram_vram_plot, 0, 1)
        else:
            # Stacked: 2 rows, 1 column
            self.graph_layout.addWidget(self.cpu_gpu_plot, 0, 0)
            self.graph_layout.addWidget(self.ram_vram_plot, 1, 0)

    def create_fallback_section(self) -> QWidget:
        """
        Create fallback text-based monitoring section.
        
        Returns:
            Widget containing text-based display
        """
        widget = QFrame()
        widget.setFrameStyle(QFrame.Shape.Box)
        widget.setStyleSheet(f"""
            QFrame {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.panel_bg)};
                border: 1px solid {self.color_scheme.to_hex(self.color_scheme.border_color)};
                border-radius: 3px;
                padding: 10px;
            }}
        """)
        
        layout = QVBoxLayout(widget)
        
        self.fallback_label = QLabel("")
        self.fallback_label.setFont(QFont("Courier", 10))
        self.fallback_label.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_accent)};")
        layout.addWidget(self.fallback_label)
        
        return widget
    
    def setup_connections(self):
        """Setup signal/slot connections."""
        self.metrics_updated.connect(self.update_display)

        # Connect persistent monitor signals
        self.persistent_monitor.connect_signals(
            metrics_callback=self.on_metrics_updated,
            error_callback=self.on_metrics_error
        )
    
    def start_monitoring(self):
        """Start the persistent monitoring thread."""
        self.persistent_monitor.start_monitoring()
        logger.debug("System monitoring started")

    def stop_monitoring(self):
        """Stop the persistent monitoring thread."""
        self.persistent_monitor.stop_monitoring()
        logger.debug("System monitoring stopped")

    def cleanup(self):
        """Clean up widget resources."""
        try:
            logger.debug("Cleaning up SystemMonitorWidget...")

            # Stop monitoring first
            self.stop_monitoring()

            # Clean up pyqtgraph plots
            if PYQTGRAPH_AVAILABLE and hasattr(self, 'cpu_plot'):
                try:
                    self.cpu_plot.clear()
                    self.ram_plot.clear()
                    self.gpu_plot.clear()
                    self.vram_plot.clear()

                    # Clear plot widgets
                    if hasattr(self, 'cpu_plot_widget'):
                        self.cpu_plot_widget.close()
                    if hasattr(self, 'ram_plot_widget'):
                        self.ram_plot_widget.close()
                    if hasattr(self, 'gpu_plot_widget'):
                        self.gpu_plot_widget.close()
                    if hasattr(self, 'vram_plot_widget'):
                        self.vram_plot_widget.close()

                except Exception as e:
                    logger.warning(f"Error cleaning up pyqtgraph plots: {e}")

            # Clear data
            if hasattr(self, 'monitor'):
                self.monitor.cpu_history.clear()
                self.monitor.ram_history.clear()
                self.monitor.gpu_history.clear()
                self.monitor.vram_history.clear()
                self.monitor.time_stamps.clear()

            logger.debug("SystemMonitorWidget cleanup completed")

        except Exception as e:
            logger.warning(f"Error during SystemMonitorWidget cleanup: {e}")
    
    def on_metrics_updated(self, metrics: dict):
        """Handle metrics update from persistent monitor thread."""
        try:
            # Update the sync monitor's history for compatibility with existing plotting code
            if metrics:
                self.monitor.cpu_history.append(metrics.get('cpu_percent', 0))
                self.monitor.ram_history.append(metrics.get('ram_percent', 0))
                self.monitor.gpu_history.append(metrics.get('gpu_percent', 0))
                self.monitor.vram_history.append(metrics.get('vram_percent', 0))
                self.monitor.time_stamps.append(time.time())

                # Update cached metrics
                self.monitor._current_metrics = metrics.copy()

            self.metrics_updated.emit(metrics)

        except Exception as e:
            logger.warning(f"Failed to process metrics update: {e}")

    def on_metrics_error(self, error_message: str):
        """Handle metrics collection error."""
        logger.warning(f"Metrics collection failed: {error_message}")
        # Continue with cached/default metrics to keep UI responsive

    def update_display(self, metrics: dict):
        """
        Update the display with new metrics.

        Args:
            metrics: Dictionary of system metrics
        """
        try:
            # Update system info
            self.update_system_info(metrics)

            if PYQTGRAPH_AVAILABLE is True:
                self._queue_pyqtgraph_plot_update(metrics)
            elif PYQTGRAPH_AVAILABLE is False:
                self.update_fallback_display(metrics)

        except Exception as e:
            logger.warning(f"Failed to update display: {e}")

    def _queue_pyqtgraph_plot_update(self, metrics: dict) -> None:
        """Coalesce plot rendering with the shared visual-frame coordinator."""

        metrics_snapshot = metrics.copy()
        queue_visual_frame_callback(
            self,
            lambda: self.update_pyqtgraph_plots(metrics_snapshot),
        )

    def _reset_plot_buffers(self):
        """Drop cached plot arrays/ranges after monitor history configuration changes."""
        self._history_length = 0
        self._history_x = None
        self._history_cpu = None
        self._history_ram = None
        self._history_gpu = None
        self._history_vram = None
        self._history_update_interval = None
        self._last_plot_history = None
        self._gpu_series_visible = False
        self._vram_series_visible = False
        try:
            for curve in (self.cpu_curve, self.gpu_curve, self.ram_curve, self.vram_curve):
                self._clear_curve(curve)
        except AttributeError:
            pass

    def update_pyqtgraph_plots(self, metrics: Optional[dict] = None):
        """Update consolidated PyQtGraph plot data at metrics cadence."""
        try:
            data_length = len(self.monitor.cpu_history)
            if data_length == 0:
                return

            update_interval = float(self.monitor_config.update_interval_seconds)
            history = float(self.monitor_config.history_duration_seconds)
            self._ensure_plot_buffers(data_length, update_interval)

            self._copy_history(self.monitor.cpu_history, self._history_cpu)
            self._copy_history(self.monitor.ram_history, self._history_ram)
            self._copy_history(self.monitor.gpu_history, self._history_gpu)
            self._copy_history(self.monitor.vram_history, self._history_vram)
            self._history_length = data_length

            if self._last_plot_history != history:
                self._apply_fixed_plot_ranges(history)

            x_view, cpu_view = self._plot_view(self._history_cpu)
            self._set_curve_data(self.cpu_curve, x_view, cpu_view)

            gpu_series_visible = self._series_has_signal(self._history_gpu)
            if gpu_series_visible:
                x_view, gpu_view = self._plot_view(self._history_gpu)
                self._set_curve_data(self.gpu_curve, x_view, gpu_view)
            elif self._gpu_series_visible:
                self._clear_curve(self.gpu_curve)
            self._gpu_series_visible = gpu_series_visible

            x_view, ram_view = self._plot_view(self._history_ram)
            self._set_curve_data(self.ram_curve, x_view, ram_view)

            vram_series_visible = self._series_has_signal(self._history_vram)
            if vram_series_visible:
                x_view, vram_view = self._plot_view(self._history_vram)
                self._set_curve_data(self.vram_curve, x_view, vram_view)
            elif self._vram_series_visible:
                self._clear_curve(self.vram_curve)
            self._vram_series_visible = vram_series_visible

        except Exception as e:
            logger.warning(f"Failed to update PyQtGraph plots: {e}")

    def _ensure_plot_buffers(self, data_length: int, update_interval: float):
        """Create or resize persistent NumPy buffers used by plot updates."""
        import numpy as _np

        if self._history_x is None or self._history_x.shape[0] != data_length:
            self._history_x = _np.zeros(data_length, dtype=_np.float64)
            self._history_cpu = _np.zeros(data_length, dtype=_np.float32)
            self._history_ram = _np.zeros(data_length, dtype=_np.float32)
            self._history_gpu = _np.zeros(data_length, dtype=_np.float32)
            self._history_vram = _np.zeros(data_length, dtype=_np.float32)
            self._history_update_interval = None

        if self._history_update_interval != update_interval:
            self._history_x[:] = (_np.arange(data_length, dtype=_np.float64) - (data_length - 1)) * update_interval
            self._history_update_interval = update_interval

    def _copy_history(self, source, target):
        """Copy a metric deque into an existing NumPy array."""
        for index, value in enumerate(source):
            try:
                target[index] = float(value)
            except (TypeError, ValueError):
                target[index] = 0.0

    def _series_has_signal(self, series) -> bool:
        """Return True when an optional metric has non-zero data."""
        try:
            return bool(series.any())
        except Exception:
            return False

    def _apply_fixed_plot_ranges(self, history: Optional[float] = None):
        """Set the fixed relative x-axis window for both plots."""
        history = float(history if history is not None else self.monitor_config.history_duration_seconds)
        try:
            self.cpu_gpu_plot.setXRange(-history, 0.0, padding=0)
            self.ram_vram_plot.setXRange(-history, 0.0, padding=0)
            self._last_plot_history = history
        except Exception:
            pass

    def _plot_sample_stride(self, data_length: int) -> int:
        """Return a stride that bounds pathological histories without degrading normal plots."""
        point_budget = max(2, int(self._plot_point_budget))
        if data_length <= point_budget:
            return 1
        return max(1, (data_length + point_budget - 1) // point_budget)

    def _plot_view(self, series):
        """Return x/y views trimmed to the point budget while preserving the newest sample."""
        stride = self._plot_sample_stride(self._history_length)
        if stride <= 1:
            return self._history_x, series

        start = (self._history_length - 1) % stride
        return self._history_x[start::stride], series[start::stride]

    def _set_curve_data(self, curve, x, y):
        try:
            curve.setData(x, y, skipFiniteCheck=True)
        except TypeError:
            curve.setData(x, y)

    def _clear_curve(self, curve):
        try:
            curve.setData([], [], skipFiniteCheck=True)
        except TypeError:
            curve.setData([], [])
    
    def update_fallback_display(self, metrics: dict):
        """
        Update fallback text display.
        
        Args:
            metrics: Dictionary of system metrics
        """
        try:
            display_text = f"""
┌─────────────────────────────────────────────────────────────────┐
│ CPU:  {self.create_text_bar(metrics.get('cpu_percent', 0))} {metrics.get('cpu_percent', 0):5.1f}%
│ RAM:  {self.create_text_bar(metrics.get('ram_percent', 0))} {metrics.get('ram_percent', 0):5.1f}% ({metrics.get('ram_used_gb', 0):.1f}/{metrics.get('ram_total_gb', 0):.1f}GB)
│ GPU:  {self.create_text_bar(metrics.get('gpu_percent', 0))} {metrics.get('gpu_percent', 0):5.1f}%
│ VRAM: {self.create_text_bar(metrics.get('vram_percent', 0))} {metrics.get('vram_percent', 0):5.1f}%
└─────────────────────────────────────────────────────────────────┘
"""
            self.fallback_label.setText(display_text)
            
        except Exception as e:
            logger.warning(f"Failed to update fallback display: {e}")
    
    def update_system_info(self, metrics: dict):
        """
        Update system information display.

        Args:
            metrics: Dictionary of system metrics
        """
        try:
            self.cpu_cores_label[1].setText(str(metrics.get('cpu_cores', 'N/A')))
            self.cpu_freq_label[1].setText(f"{metrics.get('cpu_freq_mhz', 0):.0f} MHz")

            # Update RAM info
            self.ram_total_label[1].setText(f"{metrics.get('ram_total_gb', 0):.1f} GB")
            self.ram_used_label[1].setText(f"{metrics.get('ram_used_gb', 0):.1f} GB")

            # Update GPU info if available
            if 'gpu_name' in metrics:
                gpu_name = metrics.get('gpu_name', 'N/A')
                if len(gpu_name) > 35:
                    gpu_name = gpu_name[:32] + '...'

                self.gpu_name_label[1].setText(gpu_name)
                self.gpu_temp_label[1].setText(f"{metrics.get('gpu_temp', 'N/A')}°C")
                self.vram_label[1].setText(
                    f"{metrics.get('vram_used_mb', 0):.0f} / {metrics.get('vram_total_mb', 0):.0f} MB"
                )

                # Show GPU labels
                self.gpu_name_label[0].show()
                self.gpu_name_label[1].show()
                self.gpu_temp_label[0].show()
                self.gpu_temp_label[1].show()
                self.vram_label[0].show()
                self.vram_label[1].show()
            else:
                # Hide GPU labels if no GPU
                self.gpu_name_label[0].hide()
                self.gpu_name_label[1].hide()
                self.gpu_temp_label[0].hide()
                self.gpu_temp_label[1].hide()
                self.vram_label[0].hide()
                self.vram_label[1].hide()

        except Exception as e:
            logger.warning(f"Failed to update system info: {e}")
    
    def create_text_bar(self, percent: float) -> str:
        """
        Create a text-based progress bar.
        
        Args:
            percent: Percentage value (0-100)
            
        Returns:
            Text progress bar
        """
        bar_length = 20
        filled = int(bar_length * percent / 100)
        bar = '█' * filled + '░' * (bar_length - filled)
        return f"[{bar}]"
    
    def get_ascii_header(self) -> str:
        """
        Get ASCII art header.
        
        Returns:
            ASCII art header string
        """
        return """
 ██████╗ ██████╗ ███████╗███╗   ██╗██╗  ██╗ ██████╗███████╗
██╔═══██╗██╔══██╗██╔════╝████╗  ██║██║  ██║██╔════╝██╔════╝
██║   ██║██████╔╝█████╗  ██╔██╗ ██║███████║██║     ███████╗
██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██║██║     ╚════██║
╚██████╔╝██║     ███████╗██║ ╚████║██║  ██║╚██████╗███████║
 ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝ ╚═════╝╚══════╝
        """
    
    def set_update_interval(self, interval_ms: int):
        """
        Set the update interval for monitoring.

        Args:
            interval_ms: Update interval in milliseconds
        """
        interval_seconds = interval_ms / 1000.0
        self.persistent_monitor.set_update_interval(interval_seconds)

    def update_config(self, new_config: PerformanceMonitorConfig):
        """
        Update the widget configuration and apply changes.

        Args:
            new_config: New configuration to apply
        """
        old_monitor_config = self.monitor_config
        old_sampler_config = old_monitor_config.sampler_config
        self.monitor_config = new_config
        new_sampler_config = new_config.sampler_config

        # Rebuild only when the configuration's derived sampling behavior changes.
        needs_monitor_restart = (
            old_monitor_config.update_interval_seconds
            != new_config.update_interval_seconds
            or old_monitor_config.calculated_max_data_points
            != new_config.calculated_max_data_points
            or old_sampler_config != new_sampler_config
        )

        if needs_monitor_restart:

            logger.info(
                "Updating performance monitor: %.2f FPS, %.2fs history",
                self.monitor_config.update_fps,
                self.monitor_config.history_duration_seconds,
            )

            # Stop current monitoring
            self.stop_monitoring()

            # Recalculate parameters
            update_interval = self.monitor_config.update_interval_seconds
            history_length = self.monitor_config.calculated_max_data_points

            # Create new monitors with updated config
            self.monitor = SystemMonitorCore(
                history_length=history_length,
                sampler_config=new_sampler_config,
            )
            self.persistent_monitor = PersistentSystemMonitor(
                update_interval=update_interval,
                history_length=history_length,
                sampler_config=new_sampler_config,
            )
            self._reset_plot_buffers()
            self._apply_fixed_plot_ranges()

            # Reconnect signals
            self.persistent_monitor.connect_signals(
                metrics_callback=self.on_metrics_updated,
                error_callback=self.on_metrics_error
            )

            # Restart monitoring
            self.start_monitoring()

        # Plot presentation is cheap and idempotent. Applying the complete nominal
        # config avoids a second field-dispatch table and also handles updates made
        # before the asynchronous plot widgets are ready.
        self._update_plot_appearance()

        logger.debug("Performance monitor configuration updated")

    def _update_plot_appearance(self):
        """Update plot appearance based on current configuration."""
        if not all(
            hasattr(self, attribute)
            for attribute in (
                "cpu_gpu_plot",
                "ram_vram_plot",
                "cpu_curve",
                "ram_curve",
                "gpu_curve",
                "vram_curve",
            )
        ):
            return

        colors = self.monitor_config.chart_colors
        line_width = self.monitor_config.line_width

        self._plot_opengl_enabled = self._configure_plot_acceleration()
        pg.setConfigOption("antialias", self._effective_plot_antialiasing())

        # Update curve pens
        self.cpu_curve.setPen(pg.mkPen(colors['cpu'], width=line_width))
        self.ram_curve.setPen(pg.mkPen(colors['ram'], width=line_width))
        self.gpu_curve.setPen(pg.mkPen(colors['gpu'], width=line_width))
        self.vram_curve.setPen(pg.mkPen(colors['vram'], width=line_width))
        for curve in (
            self.cpu_curve,
            self.gpu_curve,
            self.ram_curve,
            self.vram_curve,
        ):
            self._configure_plot_curve(curve)

        # Update plot grid for consolidated plots (don't change X range here - let update_pyqtgraph_plots handle it)
        plots = [self.cpu_gpu_plot, self.ram_vram_plot]
        for plot in plots:
            plot.showGrid(
                x=self.monitor_config.show_grid,
                y=self.monitor_config.show_grid,
                alpha=0.3,
            )
        self._apply_fixed_plot_ranges()
    
    def closeEvent(self, event):
        """Handle widget close event."""
        self.stop_monitoring()
        event.accept()
