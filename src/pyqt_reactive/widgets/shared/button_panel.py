"""Reusable button panel with declarative configuration.

Extracted from AbstractManagerWidget to allow any widget to use the same
button panel pattern without inheriting from the full manager.

Example:
    # Declarative configuration
    BUTTON_CONFIGS = [
        ("Refresh", "refresh", "Refresh the display"),
        ("Toggle", "toggle_layout", "Toggle layout mode"),
    ]
    
    # Create panel
    panel = ButtonPanel(
        button_configs=self.BUTTON_CONFIGS,
        style_generator=self.style_generator,
        on_action=self.handle_button_action
    )
"""

from typing import List, Tuple, Callable, Optional
from PyQt6.QtWidgets import QWidget, QGridLayout, QPushButton


class ButtonPanel(QWidget):
    """Reusable button panel with declarative configuration.
    
    Uses BUTTON_CONFIGS format: [(label, action_id, tooltip), ...]
    Supports grid layout with configurable columns.
    """
    
    def __init__(
        self,
        button_configs: List[Tuple[str, str, str]],
        on_action: Callable[[str], None],
        style_generator=None,
        grid_columns: int = 0,
        parent: Optional[QWidget] = None
    ):
        """Initialize button panel.
        
        Args:
            button_configs: List of (label, action_id, tooltip) tuples
            on_action: Callback function(action_id) when button is clicked
            style_generator: Optional style generator for button styling
            grid_columns: Number of columns (0 = single row)
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.button_configs = button_configs
        self.on_action = on_action
        self.style_generator = style_generator
        self.grid_columns = grid_columns
        self.buttons: dict = {}
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Create the button layout."""
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(5, 5, 5, 5)
        self._layout.setSpacing(5)
        
        for label, action_id, tooltip in self.button_configs:
            button = QPushButton(label)
            button.setToolTip(tooltip)
            
            if self.style_generator:
                button.setStyleSheet(self.style_generator.generate_button_style())
            
            button.clicked.connect(lambda checked, a=action_id: self.on_action(a))
            self.add_button(action_id, button)

    def add_button(self, action_id: str, button: QPushButton) -> QPushButton:
        """Append an action button using this panel's declared grid policy."""
        if action_id in self.buttons:
            raise ValueError(f"Button action already exists: {action_id!r}")

        index = len(self.buttons)
        if self.grid_columns:
            row, column = divmod(index, self.grid_columns)
        else:
            row, column = 0, index
        self._layout.addWidget(button, row, column)
        self.buttons[action_id] = button
        return button
    
    def set_button_enabled(self, action_id: str, enabled: bool):
        """Enable or disable a button by action_id."""
        if action_id in self.buttons:
            self.buttons[action_id].setEnabled(enabled)
    
    def set_button_text(self, action_id: str, text: str):
        """Update button text by action_id."""
        if action_id in self.buttons:
            self.buttons[action_id].setText(text)
    
    def get_button(self, action_id: str) -> Optional[QPushButton]:
        """Get button widget by action_id."""
        return self.buttons.get(action_id)
