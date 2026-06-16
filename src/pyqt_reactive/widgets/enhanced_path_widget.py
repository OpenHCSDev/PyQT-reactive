"""
Enhanced Path Widget for PyQt6 GUI

Provides intelligent path selection with browse button functionality.
Uses standard Qt dialogs for consistency with the rest of OpenHCS.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

from PyQt6.QtWidgets import QWidget, QLineEdit, QPushButton, QHBoxLayout, QFileDialog
from PyQt6.QtCore import pyqtSignal

from pyqt_reactive.protocols import (
    ChangeSignalEmitter,
    PyQtWidgetMeta,
    ValueGettable,
    ValueSettable,
)
from pyqt_reactive.theming import ColorScheme

# Optional path cache - stub if not available
try:
    from pyqt_reactive.core.path_cache import PathCacheKey, get_cached_dialog_path, cache_dialog_path
except ImportError:
    PathCacheKey = None  # type: ignore
    get_cached_dialog_path = lambda *args, **kwargs: None  # type: ignore
    cache_dialog_path = lambda *args, **kwargs: None  # type: ignore

from python_introspect import ParameterInfo

logger = logging.getLogger(__name__)


@dataclass
class PathBehavior:
    """Defines behavior for path widget based on parameter analysis."""
    is_directory: bool = False
    extensions: Optional[List[str]] = None
    cache_key: PathCacheKey = PathCacheKey.GENERAL
    description: str = "path"

    @classmethod
    def from_extensions(cls, extensions: List[str]) -> "PathBehavior":
        if len(extensions) == 1:
            description = f"{extensions[0].upper()} file"
        else:
            description = f"file ({', '.join(ext.upper() for ext in extensions)})"

        return cls(
            is_directory=False,
            extensions=extensions,
            cache_key=PathCacheKey.FILE_SELECTION,
            description=description,
        )

    def with_cache_key(self, cache_key: PathCacheKey) -> "PathBehavior":
        return PathBehavior(
            is_directory=self.is_directory,
            extensions=self.extensions,
            cache_key=cache_key,
            description=self.description,
        )

    @property
    def title(self) -> str:
        """Generate appropriate dialog title."""
        if self.is_directory:
            return "Select Directory"
        elif self.extensions:
            ext_str = ", ".join(self.extensions)
            return f"Select File ({ext_str})"
        else:
            return "Select Path"

    @property
    def file_filter(self) -> str:
        """Generate Qt file filter string."""
        if self.extensions:
            # Create filter like "Image Files (*.tiff *.png);;All Files (*)"
            ext_pattern = " ".join(f"*{ext}" for ext in self.extensions)
            if len(self.extensions) == 1:
                filter_name = f"{self.extensions[0].upper()} Files"
            else:
                filter_name = "Files"
            return f"{filter_name} ({ext_pattern});;All Files (*)"
        else:
            return "All Files (*)"


class PathBehaviorDetector:
    """Detects appropriate path behavior from parameter names and docstring hints."""

    @staticmethod
    def detect_behavior(param_name: str, param_info: Optional[ParameterInfo] = None) -> PathBehavior:
        """
        Detect path behavior from parameter name and optional parameter info.

        Args:
            param_name: Parameter name to analyze
            param_info: Optional parameter info with docstring description

        Returns:
            PathBehavior with detected settings
        """
        # Get base behavior from parameter name
        base_behavior = PathBehaviorDetector._detect_from_parameter_name(param_name)

        # Try to enhance with docstring info
        if param_info and param_info.description:
            docstring_behavior = PathBehaviorDetector._parse_docstring_hints(param_info.description)
            if docstring_behavior:
                if base_behavior:
                    return docstring_behavior.with_cache_key(base_behavior.cache_key)
                return docstring_behavior.with_cache_key(PathCacheKey.GENERAL)

        # Fall back to base behavior or smart default
        if base_behavior:
            return base_behavior
        return DEFAULT_PATH_BEHAVIOR

    @staticmethod
    def _parse_docstring_hints(description: str) -> Optional[PathBehavior]:
        """Parse docstring for path behavior hints."""
        desc_lower = description.lower()

        # Directory specification
        if any(pattern in desc_lower for pattern in ["directory only", "folder only", "dir only"]):
            return DIRECTORY_PATH_BEHAVIOR

        # Extension patterns: (.ext only), (.ext1, .ext2), (.ext1/.ext2), etc.
        patterns = [
            r'\(\.([a-zA-Z0-9]+(?:\s*[,/]\s*\.?[a-zA-Z0-9]+)*)\)',  # (.json, .yaml) or (.json/.yaml)
            r'\(\.([a-zA-Z0-9]+)\s+only\)',                         # (.tiff only)
            r'\(([a-zA-Z0-9]+)\s+only\)',                           # (tiff only)
            r'\.([a-zA-Z0-9]+)\s+only',                             # .tiff only
        ]

        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                ext_string = match.group(1)
                # Split by comma or slash and clean up
                raw_exts = re.split(r'[,/]', ext_string)
                extensions = [f".{ext.strip().lstrip('.')}" for ext in raw_exts if ext.strip()]

                if extensions:
                    return PathBehavior.from_extensions(extensions)

        return None

    @staticmethod
    def _detect_from_parameter_name(param_name: str) -> Optional[PathBehavior]:
        """Detect behavior from parameter name patterns."""
        tokens = PathParameterNameTokens.parse(param_name)
        role_spec = PATH_NAME_ROLE_CLASSIFIER.classify(tokens)
        if role_spec is None:
            return None
        return role_spec.behavior


class PathNameRole(Enum):
    """Nominal path behavior roles inferred from parameter-name tokens."""

    DIRECTORY = "directory"
    FILE = "file"
    PIPELINE = "pipeline"
    STEP = "step"
    FUNCTION = "function"


DIRECTORY_PATH_BEHAVIOR = PathBehavior(
    is_directory=True,
    cache_key=PathCacheKey.DIRECTORY_SELECTION,
    description="directory",
)
DEFAULT_PATH_BEHAVIOR = PathBehavior(
    is_directory=False,
    extensions=None,
    cache_key=PathCacheKey.GENERAL,
    description="file or directory",
)


@dataclass(frozen=True)
class PathNameRoleSpec:
    """One authoritative row for parameter-name path behavior inference."""

    role: PathNameRole
    tokens: frozenset[str]
    behavior: PathBehavior


PATH_NAME_ROLE_SPECS = (
    PathNameRoleSpec(
        role=PathNameRole.DIRECTORY,
        tokens=frozenset({"dir", "directory", "folder"}),
        behavior=DIRECTORY_PATH_BEHAVIOR,
    ),
    PathNameRoleSpec(
        role=PathNameRole.FILE,
        tokens=frozenset({"file", "filepath", "filename"}),
        behavior=PathBehavior(
            is_directory=False,
            cache_key=PathCacheKey.FILE_SELECTION,
            description="file",
        ),
    ),
    PathNameRoleSpec(
        role=PathNameRole.PIPELINE,
        tokens=frozenset({"pipeline"}),
        behavior=PathBehavior(
            is_directory=False,
            cache_key=PathCacheKey.PIPELINE_FILES,
            description="pipeline file",
        ),
    ),
    PathNameRoleSpec(
        role=PathNameRole.STEP,
        tokens=frozenset({"step"}),
        behavior=PathBehavior(
            is_directory=False,
            cache_key=PathCacheKey.STEP_SETTINGS,
            description="step file",
        ),
    ),
    PathNameRoleSpec(
        role=PathNameRole.FUNCTION,
        tokens=frozenset({"function", "func"}),
        behavior=PathBehavior(
            is_directory=False,
            cache_key=PathCacheKey.FUNCTION_PATTERNS,
            description="function file",
        ),
    ),
)


@dataclass(frozen=True)
class PathParameterNameTokens:
    """Boundary parse of external parameter names into exact tokens."""

    values: frozenset[str]

    @classmethod
    def parse(cls, param_name: str) -> "PathParameterNameTokens":
        camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", param_name)
        return cls(frozenset(re.findall(r"[a-z0-9]+", camel_split.lower())))

    def contains_any(self, candidates: frozenset[str]) -> bool:
        return bool(self.values.intersection(candidates))


class PathNameRoleClassifier:
    """Classify parsed path-name tokens into a nominal behavior role."""

    def classify(self, tokens: PathParameterNameTokens) -> PathNameRoleSpec | None:
        for role_spec in PATH_NAME_ROLE_SPECS:
            if tokens.contains_any(role_spec.tokens):
                return role_spec
        return None


PATH_NAME_ROLE_CLASSIFIER = PathNameRoleClassifier()


class EnhancedPathWidget(
    QWidget,
    ValueGettable,
    ValueSettable,
    ChangeSignalEmitter,
    metaclass=PyQtWidgetMeta,
):
    """Enhanced path widget with browse button using standard Qt dialogs."""

    path_changed = pyqtSignal(str)

    def __init__(
        self,
        param_name: str,
        current_value: Path | str | None,
        param_info: Optional[ParameterInfo] = None,
        color_scheme=None,
    ):
        """
        Initialize enhanced path widget.

        Args:
            param_name: Parameter name for behavior detection
            current_value: Current path value
            param_info: Optional parameter info with docstring
            color_scheme: Color scheme for styling
        """
        super().__init__()
        self.behavior = PathBehaviorDetector.detect_behavior(param_name, param_info)
        self.color_scheme = color_scheme or ColorScheme()

        # Layout: [QLineEdit] [Browse Button]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText(f"Enter {self.behavior.description} path...")
        self.browse_button = QPushButton("📁 Browse")
        self.browse_button.setMaximumWidth(80)

        layout.addWidget(self.path_input, 1)
        layout.addWidget(self.browse_button, 0)

        self._apply_styling()
        self._setup_signals()
        self.set_path(current_value)

    def _apply_styling(self):
        """Apply color scheme styling to widgets."""
        self.path_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.input_bg)};
                color: {self.color_scheme.to_hex(self.color_scheme.input_text)};
                border: 1px solid {self.color_scheme.to_hex(self.color_scheme.input_border)};
                border-radius: 3px; padding: 5px; font-family: 'Courier New', monospace;
            }}
        """)

        self.browse_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.button_normal_bg)};
                color: {self.color_scheme.to_hex(self.color_scheme.button_text)};
                border: 1px solid {self.color_scheme.to_hex(self.color_scheme.input_border)};
                border-radius: 3px; padding: 5px 10px; font-size: 11px;
            }}
        """)

    def _setup_signals(self):
        """Setup signal connections."""
        self.path_input.textChanged.connect(self._on_text_changed)
        self.browse_button.clicked.connect(self._open_dialog)

    def _on_text_changed(self, text: str):
        """Handle text change in path input."""
        self.path_changed.emit(text)

    def set_path(self, value: Path | str | None) -> None:
        """Set path value without triggering signals."""
        self.path_input.blockSignals(True)
        try:
            if value is not None:
                # Set actual value
                text = str(value)
                self.path_input.setText(text)
            else:
                # For None values, clear the text to show placeholder
                self.path_input.clear()
        finally:
            self.path_input.blockSignals(False)

    def get_path(self) -> str | None:
        """Get current path value, returning None for empty strings."""
        text = self.path_input.text().strip()
        if text == "":
            return None
        return text

    def get_value(self) -> str | None:
        """Implement ValueGettable ABC - alias for get_path()."""
        return self.get_path()

    def set_value(self, value: Path | str | None) -> None:
        """Implement ValueSettable ABC - alias for set_path()."""
        self.set_path(value)

    def connect_change_signal(self, callback: Callable[[str], None]) -> None:
        """Implement ChangeSignalEmitter ABC."""
        self.path_changed.connect(callback)

    def disconnect_change_signal(self, callback: Callable[[str], None]) -> None:
        """Implement ChangeSignalEmitter ABC."""
        try:
            self.path_changed.disconnect(callback)
        except TypeError:
            pass

    def _open_dialog(self):
        """Open appropriate Qt dialog based on behavior."""
        try:
            # Get cached initial directory
            initial_dir = str(get_cached_dialog_path(self.behavior.cache_key, fallback=Path.home()))

            # Use None as parent to create a clean, top-level dialog
            # This prevents inheriting the dark styling from nested containers
            # and matches the simple appearance of ServiceAdapter dialogs
            parent = None

            if self.behavior.is_directory:
                # Use directory dialog
                selected_path = QFileDialog.getExistingDirectory(
                    parent,
                    self.behavior.title,
                    initial_dir
                )
            else:
                # Use file dialog
                selected_path, _ = QFileDialog.getOpenFileName(
                    parent,
                    self.behavior.title,
                    initial_dir,
                    self.behavior.file_filter
                )

            if selected_path:
                path_obj = Path(selected_path)
                self.set_path(path_obj)
                self.path_changed.emit(str(path_obj))

                # Cache the selection (directory for files, path itself for directories)
                cache_path = path_obj.parent if path_obj.is_file() else path_obj
                cache_dialog_path(self.behavior.cache_key, cache_path)

        except Exception as e:
            logger.error(f"Failed to open dialog: {e}")


# Register EnhancedPathWidget as implementing ValueGettable and ValueSettable
from pyqt_reactive.protocols import ValueGettable, ValueSettable
ValueGettable.register(EnhancedPathWidget)
ValueSettable.register(EnhancedPathWidget)
