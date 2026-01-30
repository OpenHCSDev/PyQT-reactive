"""
Example: Tear-off tabs demonstration.

This example shows how to use TearOffTabWidget to create Chrome-style
detachable tabs that can be dragged between windows.

Run with:
    python tear_off_tabs_example.py
"""

import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, 
    QLabel, QTextEdit, QPushButton
)
from PyQt6.QtCore import Qt

# Add pyqt-reactive to path (adjust as needed)
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from pyqt_reactive.widgets.shared.tear_off_tab_widget import TearOffTabWidget


class DemoTab(QWidget):
    """Demo content for a tab."""
    
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        
        layout = QVBoxLayout(self)
        
        label = QLabel(f"This is tab: {name}")
        label.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(label)
        
        info = QLabel(
            f"Try dragging this tab out of the tab bar to tear it off!\n"
            f"You can also drag it into another window's tab bar to dock it."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        
        text_edit = QTextEdit()
        text_edit.setPlaceholderText(f"Type something in {name}...")
        layout.addWidget(text_edit)


class MainWindow(QMainWindow):
    """Main window with tear-off tabs."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tear-Off Tabs Demo - Window 1")
        self.resize(800, 600)
        
        # Create central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Create tear-off tab widget
        self.tabs = TearOffTabWidget()
        
        # Add callback for when tab is torn off
        self.tabs.tab_torn_off.connect(self._on_tab_torn_off)
        self.tabs.tab_docked.connect(self._on_tab_docked)
        
        # Add some demo tabs
        self.tabs.addTab(DemoTab("Config"), "Config")
        self.tabs.addTab(DemoTab("Settings"), "Settings")
        self.tabs.addTab(DemoTab("Advanced"), "Advanced")
        
        layout.addWidget(self.tabs)
        
        # Add button to create second window
        btn = QPushButton("Open Second Window")
        btn.clicked.connect(self._open_second_window)
        layout.addWidget(btn)
        
        self.second_window = None
        
    def _on_tab_torn_off(self, tab_widget, tab_text):
        """Called when a tab is torn off."""
        print(f"Tab torn off: {tab_text}")
        
    def _on_tab_docked(self, tab_widget, tab_text, index):
        """Called when a tab is docked into this window."""
        print(f"Tab docked: {tab_text} at index {index}")
        
    def _open_second_window(self):
        """Open a second window with tear-off tabs."""
        self.second_window = SecondWindow()
        self.second_window.show()


class SecondWindow(QMainWindow):
    """Second window for cross-window drag testing."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tear-Off Tabs Demo - Window 2")
        self.resize(800, 600)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        info = QLabel(
            "This is the second window.\n"
            "Drag tabs from Window 1 into this window's tab bar!"
        )
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)
        
        # Create tear-off tab widget
        self.tabs = TearOffTabWidget()
        
        # Add some initial tabs
        self.tabs.addTab(DemoTab("Panel A"), "Panel A")
        self.tabs.addTab(DemoTab("Panel B"), "Panel B")
        
        layout.addWidget(self.tabs)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set up logging to see debug output
    import logging
    logging.basicConfig(level=logging.DEBUG)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())
