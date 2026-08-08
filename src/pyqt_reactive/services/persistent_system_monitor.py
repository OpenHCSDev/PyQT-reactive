"""
Persistent System Monitor for PyQt GUI

Uses a single persistent QThread to continuously collect system metrics
without creating/destroying threads repeatedly. This prevents UI hanging
and provides smooth, responsive performance monitoring.
"""

import logging

from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker, Qt

from pyqt_reactive.services.system_metrics_sampler import (
    SystemMetrics,
    SystemMetricsSampler,
)
from pyqt_reactive.services.system_monitor_core import (
    SystemMetricsHistory,
    SystemMonitorCore,
)

logger = logging.getLogger(__name__)


class PersistentSystemMonitorThread(QThread):
    """
    Persistent thread that continuously collects system metrics.
    
    This thread stays alive and runs a continuous loop, collecting metrics
    at regular intervals and emitting signals with the results. This is much
    more efficient than creating/destroying threads repeatedly.
    """
    
    # Signals
    metrics_updated = pyqtSignal(object)  # Emits SystemMetrics.
    error_occurred = pyqtSignal(str)    # Emitted when an error occurs
    
    def __init__(
        self,
        update_interval: float = 1.0,
        history_length: int = 60,
        *,
        sampler: SystemMetricsSampler,
    ):
        """
        Initialize the persistent monitor thread.
        
        Args:
            update_interval: Time between updates in seconds
            history_length: Number of historical data points to keep
        """
        super().__init__()
        
        self.update_interval = update_interval
        self._stop_requested = False
        self._sampler = sampler
        
        # Thread-safe data storage
        self._mutex = QMutex()
        self._history = SystemMonitorCore(history_length=history_length)
    
    def run(self):
        """Main thread loop - continuously collect metrics."""
        logger.debug("Persistent system monitor thread started")

        while not self._stop_requested:
            try:
                # Collect all metrics
                metrics = self._collect_metrics()

                # Update history with thread safety
                with QMutexLocker(self._mutex):
                    self._history.record_metrics(metrics)

                # Emit signal with new metrics
                self.metrics_updated.emit(metrics)

                # Sleep for the update interval with frequent stop checks
                sleep_ms = int(self.update_interval * 1000)
                sleep_chunks = max(1, sleep_ms // 100)  # Check every 100ms
                chunk_size = sleep_ms // sleep_chunks

                for _ in range(sleep_chunks):
                    if self._stop_requested:
                        break
                    self.msleep(chunk_size)

            except Exception as e:
                logger.warning(f"Error collecting system metrics: {e}")
                self.error_occurred.emit(str(e))
                # Sleep longer on error to avoid spam, but still check for stop
                for _ in range(20):  # 20 * 100ms = 2 seconds
                    if self._stop_requested:
                        break
                    self.msleep(100)

        logger.debug("Persistent system monitor thread stopped")
        self._sampler.close()
    
    def _collect_metrics(self) -> SystemMetrics:
        """Collect all system metrics in one go."""
        try:
            return self._sampler.collect_metrics()
        except Exception as e:
            logger.warning(f"Error in metrics collection: {e}")
            return SystemMetrics.error()
    
    def stop_monitoring(self):
        """Request the thread to stop monitoring."""
        self._stop_requested = True
        self._sampler.close()
    
    def get_current_metrics(self) -> SystemMetrics:
        """Get the current cached metrics (thread-safe)."""
        with QMutexLocker(self._mutex):
            return self._history.get_metrics()

    def get_history_data(self) -> SystemMetricsHistory:
        """Get historical data (thread-safe)."""
        with QMutexLocker(self._mutex):
            return self._history.get_history_data()
    
    def set_update_interval(self, interval: float):
        """Set the update interval in seconds."""
        self.update_interval = interval


class PersistentSystemMonitor:
    """
    System monitor that uses a persistent background thread.
    
    This provides a simple interface to the persistent monitoring thread,
    ensuring the UI never blocks during metrics collection.
    """
    
    def __init__(
        self,
        thread: PersistentSystemMonitorThread,
    ):
        """
        Initialize the persistent system monitor.

        Args:
            thread: Configured execution thread owned by this lifecycle wrapper.
        """
        self.thread = thread
        self._is_running = False

    def __del__(self):
        """Destructor - ensure thread is stopped."""
        try:
            self.stop_monitoring()
        except:
            pass  # Ignore errors during destruction
    
    def start_monitoring(self):
        """Start the monitoring thread."""
        if not self._is_running:
            self.thread.start()
            self._is_running = True
            logger.debug("Persistent system monitor started")
    
    def stop_monitoring(self):
        """Stop the monitoring thread."""
        if self._is_running:
            logger.debug("Stopping persistent system monitor...")
            self.thread.stop_monitoring()

            # Wait for clean shutdown with shorter timeout
            if not self.thread.wait(2000):  # Wait up to 2 seconds
                logger.warning("System monitor thread did not stop cleanly, terminating...")
                self.thread.terminate()
                self.thread.wait(1000)  # Give terminate a chance

            self._is_running = False
            logger.debug("Persistent system monitor stopped")
    
    def get_current_metrics(self) -> SystemMetrics:
        """Get current metrics without blocking."""
        return self.thread.get_current_metrics()
    
    def get_history_data(self) -> SystemMetricsHistory:
        """Get historical data without blocking."""
        return self.thread.get_history_data()
    
    def connect_signals(self, metrics_callback=None, error_callback=None):
        """Connect to thread signals."""
        if metrics_callback:
            self.thread.metrics_updated.connect(metrics_callback, Qt.ConnectionType.QueuedConnection)
        if error_callback:
            self.thread.error_occurred.connect(error_callback, Qt.ConnectionType.QueuedConnection)
    
    def set_update_interval(self, interval: float):
        """Set the update interval."""
        self.thread.set_update_interval(interval)
