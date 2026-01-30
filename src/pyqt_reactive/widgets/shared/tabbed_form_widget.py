"""
TabbedFormWidget - Reusable tabbed widget for ObjectState forms.

Provides a clean abstraction for creating tabbed interfaces where each tab
shows one or more ParameterFormManagers, all sharing the same ObjectState.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Any
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QScrollArea
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QIcon

from pyqt_reactive.forms import ParameterFormManager, FormManagerConfig
from pyqt_reactive.theming import StyleSheetGenerator


@dataclass
class TabConfig:
    """Configuration for a single tab in TabbedFormWidget.
    
    A tab can show:
    - A single nested config: field_ids=["napari_streaming_config"]
    - Multiple nested configs: field_ids=["napari_streaming_config", "fiji_streaming_config"]
    - Specific fields from different configs: field_ids=["config_a.host", "config_b.host"]
    """
    name: str                                    # Tab display name
    field_ids: List[str]                         # Dotted paths - each gets its own PFM
    icon: Optional[QIcon] = None                 # Optional tab icon
    tooltip: Optional[str] = None                # Optional tab tooltip


@dataclass
class TabbedFormConfig:
    """Configuration for TabbedFormWidget."""
    tabs: List[TabConfig]                                       # Tab configurations
    shared_field_ids: List[str] = field(default_factory=list)  # Fields to show above tabs
    color_scheme: Optional[Any] = None                          # Color scheme for all PFMs
    use_scroll_area: bool = True                                # Wrap each tab in scroll area
    header_widgets: List[QWidget] = field(default_factory=list) # Widgets to show right-aligned in tab bar row


class TabbedFormWidget(QWidget):
    """
    Reusable tabbed widget for ObjectState forms.
    
    Creates a tabbed interface where each tab contains one or more ParameterFormManagers,
    all sharing the same ObjectState instance. Supports:
    - Field-scoped tabs (each tab shows a different nested config)
    - Multiple configs per tab
    - Shared header fields above the tab widget
    - Automatic signal aggregation from all child PFMs
    
    Example:
        config = TabbedFormConfig(
            tabs=[
                TabConfig(name="Napari", field_ids=["napari_streaming_config"]),
                TabConfig(name="Fiji", field_ids=["fiji_streaming_config"]),
            ],
            color_scheme=color_scheme
        )
        widget = TabbedFormWidget(state=object_state, config=config)
    """
    
    # Aggregate signal from all child PFMs
    parameter_changed = pyqtSignal(str, object)
    
    def __init__(
        self,
        state: Any,  # ObjectState instance
        config: TabbedFormConfig,
        parent: Optional[QWidget] = None
    ):
        """
        Initialize TabbedFormWidget.
        
        Args:
            state: ObjectState instance shared by all PFMs
            config: TabbedFormConfig specifying tabs and shared fields
            parent: Optional parent widget
        """
        super().__init__(parent)
        
        self.state = state
        self.config = config
        self.shared_forms: List[ParameterFormManager] = []
        self.tab_forms: List[ParameterFormManager] = []  # One PFM per tab
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the UI with shared forms and tab widget."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Create shared forms (above tabs)
        if self.config.shared_field_ids:
            for field_id in self.config.shared_field_ids:
                form = self._create_form(field_id)
                self.shared_forms.append(form)
                layout.addWidget(form)

        # Create tab widget
        self.tab_widget = QTabWidget()

        # Apply styling if color_scheme provided
        if self.config.color_scheme:
            style_gen = StyleSheetGenerator(self.config.color_scheme)
            self.tab_widget.setStyleSheet(style_gen.generate_tab_widget_style())

        # Create tabs
        for tab_config in self.config.tabs:
            tab_widget = self._create_tab(tab_config)

            # Add tab with optional icon
            if tab_config.icon:
                self.tab_widget.addTab(tab_widget, tab_config.icon, tab_config.name)
            else:
                self.tab_widget.addTab(tab_widget, tab_config.name)

            # Set tooltip if provided
            if tab_config.tooltip:
                tab_index = self.tab_widget.count() - 1
                self.tab_widget.setTabToolTip(tab_index, tab_config.tooltip)

        # Add header widgets to tab bar corner (right-aligned on same row as tabs)
        if self.config.header_widgets:
            corner_widget = QWidget()
            corner_layout = QHBoxLayout(corner_widget)
            corner_layout.setContentsMargins(0, 0, 0, 0)
            corner_layout.setSpacing(5)

            for widget in self.config.header_widgets:
                corner_layout.addWidget(widget)

            self.tab_widget.setCornerWidget(corner_widget, Qt.Corner.TopRightCorner)

        layout.addWidget(self.tab_widget, 1)  # Stretch factor = 1
    
    def _create_tab(self, tab_config: TabConfig) -> QWidget:
        """Create a tab widget containing ONE PFM that renders specified nested fields as GroupBoxWithHelp."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Create ONE PFM for this tab that shows only the specified field_ids as nested GroupBoxWithHelp
        form = self._create_form(tab_config.field_ids)
        self.tab_forms.append(form)

        # Wrap in scroll area if configured
        if self.config.use_scroll_area:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setWidget(form)
            layout.addWidget(scroll, 1)
        else:
            layout.addWidget(form, 1)

        return container

    def _create_form(self, field_ids: List[str]) -> ParameterFormManager:
        """
        Create a ParameterFormManager that renders specific nested fields as GroupBoxWithHelp.

        Instead of scoping the PFM with field_id, we create a root PFM and use exclude_params
        to show only the desired nested fields. This allows PFM to detect them as nested fields
        and create GroupBoxWithHelp containers with proper title, help button, enabled checkbox, etc.

        Args:
            field_ids: List of field names to render as nested GroupBoxWithHelp containers

        Returns:
            ParameterFormManager instance
        """
        # Get all top-level field names from the root object
        all_field_names = self._get_all_field_names()

        # Exclude all fields EXCEPT the ones we want to show in this tab
        exclude_params = [f for f in all_field_names if f not in field_ids]

        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"TabbedFormWidget._create_form: field_ids={field_ids}")
        logger.debug(f"TabbedFormWidget._create_form: all_field_names={all_field_names}")
        logger.debug(f"TabbedFormWidget._create_form: exclude_params={exclude_params}")

        form_config = FormManagerConfig(
            parent=self,
            color_scheme=self.config.color_scheme,
            field_id='',  # Empty field_id = root PFM (sees full object)
            exclude_params=exclude_params,  # Hide all except desired fields
            use_scroll_area=False  # We handle scrolling at the tab level
        )

        form = ParameterFormManager(state=self.state, config=form_config)

        # Connect parameter_changed signal to aggregate signal
        form.parameter_changed.connect(self._on_parameter_changed)

        return form

    def _get_all_field_names(self) -> List[str]:
        """
        Get all top-level field names from the root object.

        Returns:
            List of field names
        """
        obj = self.state.object_instance

        # Try dataclass fields first
        if hasattr(obj, '__dataclass_fields__'):
            return list(obj.__dataclass_fields__.keys())

        # Fall back to instance attributes (for SimpleNamespace, etc.)
        elif hasattr(obj, '__dict__'):
            return list(vars(obj).keys())

        # Last resort: empty list
        return []

    def _on_parameter_changed(self, param_name: str, value: Any):
        """Forward parameter changes from child PFMs to aggregate signal."""
        self.parameter_changed.emit(param_name, value)

    def get_all_forms(self) -> List[ParameterFormManager]:
        """
        Get all ParameterFormManager instances (shared + tabs).

        Returns:
            List of all PFM instances in this widget
        """
        all_forms = list(self.shared_forms)
        all_forms.extend(self.tab_forms)  # tab_forms is now a flat list of PFMs
        return all_forms

    def get_tab_form(self, tab_index: int) -> Optional[ParameterFormManager]:
        """
        Get PFM for a specific tab.

        Args:
            tab_index: Index of the tab

        Returns:
            PFM instance for that tab, or None if invalid index
        """
        if 0 <= tab_index < len(self.tab_forms):
            return self.tab_forms[tab_index]
        return None

    def get_current_tab_form(self) -> Optional[ParameterFormManager]:
        """
        Get PFM for the currently selected tab.

        Returns:
            PFM instance for the current tab, or None
        """
        return self.get_tab_form(self.tab_widget.currentIndex())

