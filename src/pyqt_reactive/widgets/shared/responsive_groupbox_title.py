"""Responsive title layout for GroupBoxWithHelp."""

from typing import List, Optional, Tuple

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from pyqt_reactive.widgets.shared.responsive_layout_widgets import StagedWrapLayout


class ResponsiveGroupBoxTitle(QWidget):
    """
    Responsive title widget that switches between 1-row and 2-row layout.
    
    Row 1: [Title] [Help] [inline widgets]
    Row 2: [Reset All] [Enabled] etc. - only when narrow
    """

    TITLE_GROUP = "title"
    HELP_GROUP = "help"
    INLINE_GROUP = "inline"
    RIGHT_GROUP = "right"
    
    def __init__(self, parent=None):
        super().__init__(parent)

        # Transparent background so scope-tinted background shows through
        self.setAutoFillBackground(False)
        self.setStyleSheet("background-color: transparent;")

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(2)

        self._staged_layout = StagedWrapLayout(parent=self, spacing=5)
        self._main_layout.addWidget(self._staged_layout)
        
        # Storage
        self._title_widget: Optional[QWidget] = None
        self._help_widget: Optional[QWidget] = None
        self._inline_widgets: List[Tuple[QWidget, int]] = []
        self._right_widgets: List[Tuple[QWidget, int]] = []

        self._title_group = QWidget()
        self._title_layout = QHBoxLayout(self._title_group)
        self._title_layout.setContentsMargins(0, 0, 0, 0)
        self._title_layout.setSpacing(5)

        self._help_group = QWidget()
        self._help_layout = QHBoxLayout(self._help_group)
        self._help_layout.setContentsMargins(0, 0, 0, 0)
        self._help_layout.setSpacing(5)

        self._inline_group = QWidget()
        self._inline_layout = QHBoxLayout(self._inline_group)
        self._inline_layout.setContentsMargins(0, 0, 0, 0)
        self._inline_layout.setSpacing(5)
        self._inline_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._right_group = QWidget()
        self._right_layout = QHBoxLayout(self._right_group)
        self._right_layout.setContentsMargins(0, 0, 0, 0)
        self._right_layout.setSpacing(5)

        # Help button stays inline with title (always left aligned)
        self._help_inline = True
        
        # Debounce timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._check_switch)
        
        if parent:
            parent.installEventFilter(self)
    
    def set_title_widget(self, widget):
        self._title_widget = widget
        self._title_layout.addWidget(widget)
        self._refresh_groups()
    
    def set_help_widget(self, widget):
        self._help_widget = widget
        if self._help_inline:
            self._title_layout.addWidget(widget)
        else:
            self._help_layout.addWidget(widget)
        self._refresh_groups()
    
    def add_right_widget(self, widget, stretch=0):
        self._right_widgets.append((widget, stretch))
        self._right_layout.addWidget(widget, stretch)
        if (
            stretch > 0
            or widget.sizePolicy().expandingDirections()
            & Qt.Orientation.Horizontal
        ):
            group_policy = self._right_group.sizePolicy()
            group_policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
            self._right_group.setSizePolicy(group_policy)
        self._refresh_groups()
    
    def add_inline_widget(self, widget, stretch=0):
        """Add widget that stays with title in row1 (doesn't move to row2)."""
        self._inline_widgets.append((widget, stretch))
        self._inline_layout.addWidget(widget, stretch)
        self._refresh_groups()
    
    def _check_switch(self):
        self._refresh_groups()
    
    def _do_switch(self):
        self._refresh_groups()
    
    def eventFilter(self, a0, a1):
        if a1 is not None and a1.type() == a1.Type.Resize:
            self._timer.start(100)
        return super().eventFilter(a0, a1)
    
    def _refresh_groups(self):
        if self._help_inline:
            groups = [
                (self.TITLE_GROUP, self._title_group),
                (self.INLINE_GROUP, self._inline_group),
                (self.RIGHT_GROUP, self._right_group),
            ]
            stay_priority = [self.TITLE_GROUP, self.INLINE_GROUP, self.RIGHT_GROUP]
        else:
            groups = [
                (self.TITLE_GROUP, self._title_group),
                (self.HELP_GROUP, self._help_group),
                (self.INLINE_GROUP, self._inline_group),
                (self.RIGHT_GROUP, self._right_group),
            ]
            stay_priority = [self.TITLE_GROUP, self.HELP_GROUP, self.INLINE_GROUP, self.RIGHT_GROUP]

        self._staged_layout.set_groups(
            groups,
            stay_priority,
            right_align_names=[self.RIGHT_GROUP],
        )
