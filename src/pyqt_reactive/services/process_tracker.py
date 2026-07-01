"""
Process Tracker Utility

Tracks which processes are currently alive for log file status indication.
Used by log viewer to distinguish logs from running vs terminated processes.
"""

import logging
import re
from pathlib import Path
from typing import Iterable, Set, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProcessInfo:
    """Information about a tracked process."""
    pid: int
    name: str
    status: str
    create_time: float


class ProcessTracker:
    """
    Tracks which processes are currently alive.
    
    Used to determine if log files correspond to running or terminated processes.
    """
    
    def __init__(self):
        """Initialize process tracker."""
        self.alive_pids: Set[int] = set()
        self.process_info: dict[int, ProcessInfo] = {}
        self._psutil_available = False
        
        # Check if psutil is available
        try:
            import psutil
            self._psutil_available = True
            logger.debug("ProcessTracker initialized with psutil support")
        except ImportError:
            logger.warning("psutil not available - process tracking disabled")
    
    def update(self, target_pids: Iterable[int] | None = None) -> bool:
        """Update tracked process state.

        Args:
            target_pids: Optional PID set to check directly. When provided,
                avoids scanning every process on the machine.

        Returns:
            True when tracked alive/dead state changed.
        """
        if not self._psutil_available:
            return False
        
        try:
            import psutil

            old_alive_pids = self.alive_pids
            target_pid_set = set(target_pids) if target_pids is not None else None
            
            new_alive_pids = set()
            new_process_info = {}

            if target_pid_set is None:
                process_iter = psutil.process_iter(['pid', 'name', 'status', 'create_time'])
                for proc in process_iter:
                    try:
                        pid = proc.info['pid']
                        new_alive_pids.add(pid)
                        new_process_info[pid] = ProcessInfo(
                            pid=pid,
                            name=proc.info.get('name', 'unknown'),
                            status=proc.info.get('status', 'unknown'),
                            create_time=proc.info.get('create_time', 0),
                        )
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            else:
                for pid in target_pid_set:
                    try:
                        proc = psutil.Process(pid)
                        new_alive_pids.add(pid)
                        new_process_info[pid] = ProcessInfo(
                            pid=pid,
                            name=proc.name(),
                            status=proc.status(),
                            create_time=proc.create_time(),
                        )
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass
            
            self.alive_pids = new_alive_pids
            self.process_info = new_process_info
            changed = old_alive_pids != new_alive_pids
            
            logger.debug(f"Updated process tracker: {len(self.alive_pids)} alive processes")
            return changed

        except Exception as e:
            logger.warning(f"Failed to update process tracker: {e}")
            return False
    
    def is_alive(self, pid: Optional[int]) -> bool:
        """
        Check if a PID is currently alive.
        
        Args:
            pid: Process ID to check (None returns False)
            
        Returns:
            bool: True if process is alive, False otherwise
        """
        if pid is None or not self._psutil_available:
            return False
        return pid in self.alive_pids
    
    def get_process_info(self, pid: int) -> Optional[ProcessInfo]:
        """
        Get information about a process.
        
        Args:
            pid: Process ID
            
        Returns:
            ProcessInfo if process is alive, None otherwise
        """
        return self.process_info.get(pid)
    
    def get_status_icon(self, pid: Optional[int]) -> str:
        """
        Get status icon for a process.
        
        Args:
            pid: Process ID (None returns unknown icon)
            
        Returns:
            str: Status icon (🟢 alive, ⚫ dead, ❓ unknown)
        """
        if pid is None or not self._psutil_available:
            return "❓"
        return "🟢" if self.is_alive(pid) else "⚫"
    
    def get_status_text(self, pid: Optional[int]) -> str:
        """
        Get human-readable status text for a process.
        
        Args:
            pid: Process ID (None returns "Unknown")
            
        Returns:
            str: Status text ("Running", "Terminated", "Unknown")
        """
        if pid is None or not self._psutil_available:
            return "Unknown"
        return "Running" if self.is_alive(pid) else "Terminated"


def extract_pid_from_log_filename(log_path: Path) -> Optional[int]:
    """
    Extract PID from application log filename.
    
    Supports various log filename patterns:
    - app_unified_20251007_102845_worker_12345.log
    - zmq_worker_exec_abc123_worker_12345.log
    - app_worker_12345.log
    
    Args:
        log_path: Path to log file
        
    Returns:
        int: Extracted PID, or None if no PID found
    """
    # Pattern to match worker PID in filename
    match = re.search(r'worker_(\d+)', log_path.name)
    if match:
        return int(match.group(1))
    
    # Pattern to match PID in other formats (e.g., process_12345.log)
    match = re.search(r'process_(\d+)', log_path.name)
    if match:
        return int(match.group(1))
    
    # Pattern to match PID at end of filename (e.g., server_12345.log)
    match = re.search(r'_(\d+)\.log$', log_path.name)
    if match:
        pid_candidate = int(match.group(1))
        # Only return if it looks like a PID (not a timestamp)
        if pid_candidate < 1000000:  # PIDs are typically < 1M
            return pid_candidate
    
    return None


def get_log_display_name(log_path: Path, process_tracker: ProcessTracker) -> str:
    """
    Get display name for log file with process status indicator.
    
    Args:
        log_path: Path to log file
        process_tracker: ProcessTracker instance
        
    Returns:
        str: Display name with status icon (e.g., "🟢 worker_12345.log")
    """
    pid = extract_pid_from_log_filename(log_path)
    icon = process_tracker.get_status_icon(pid)
    return f"{icon} {log_path.name}"


def get_log_tooltip(log_path: Path, process_tracker: ProcessTracker) -> str:
    """
    Get tooltip text for log file with process information.
    
    Args:
        log_path: Path to log file
        process_tracker: ProcessTracker instance
        
    Returns:
        str: Tooltip text with process status and info
    """
    pid = extract_pid_from_log_filename(log_path)
    
    if pid is None:
        return f"Log file: {log_path.name}\nProcess: Unknown"
    
    status = process_tracker.get_status_text(pid)
    tooltip = f"Log file: {log_path.name}\nPID: {pid}\nStatus: {status}"
    
    # Add additional process info if available
    proc_info = process_tracker.get_process_info(pid)
    if proc_info:
        tooltip += f"\nProcess: {proc_info.name}"
    
    return tooltip
