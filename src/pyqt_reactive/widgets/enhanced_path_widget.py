"""
Enhanced Path Widget for PyQt6 GUI

Provides intelligent path selection with browse button functionality.
Uses standard Qt dialogs for consistency with the host application.
"""

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from metaclass_registry import AutoRegisterMeta
from PyQt6.QtCore import QSize, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QWidget
from python_introspect import ParameterInfo

from formbridge.core.path_cache import (
    DirectorySelection,
    FileSelection,
    General,
    PathCacheKey,
    cache_path,
    get_initial_path,
)
from pyqt_reactive.protocols import (
    ChangeSignalEmitter,
    PlaceholderStateMixin,
    PyQtWidgetMeta,
    ValueGettable,
    ValueSettable,
)
from pyqt_reactive.theming import ColorScheme

logger = logging.getLogger(__name__)


def _role_name(name: str, cls: type) -> str | None:
    return None if "__registry__" in vars(cls) else name


@dataclass(frozen=True, slots=True)
class PathBehavior:
    """Defines behavior for path widget based on parameter analysis."""

    is_directory: bool = False
    extensions: tuple[str, ...] | None = None
    cache_key: type[PathCacheKey] = General
    description: str = "path"

    @classmethod
    def from_extensions(cls, extensions: Sequence[str]) -> "PathBehavior":
        declared_extensions = tuple(extensions)
        if len(declared_extensions) == 1:
            description = f"{declared_extensions[0].upper()} file"
        else:
            description = f"file ({', '.join(ext.upper() for ext in declared_extensions)})"

        return cls(
            is_directory=False,
            extensions=declared_extensions,
            cache_key=FileSelection,
            description=description,
        )

    def with_cache_key(self, cache_key: type[PathCacheKey]) -> "PathBehavior":
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
    def detect_behavior(
        param_name: str,
        param_info: ParameterInfo | None = None,
    ) -> PathBehavior:
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
                return docstring_behavior.with_cache_key(General)

        # Fall back to base behavior or smart default
        if base_behavior:
            return base_behavior
        return DEFAULT_PATH_BEHAVIOR

    @staticmethod
    def _parse_docstring_hints(description: str) -> PathBehavior | None:
        """Parse docstring for path behavior hints."""
        desc_lower = description.lower()

        # Directory specification derives its accepted words from the role owner.
        if any(f"{token} only" in desc_lower for token in DirectoryPathRole.tokens):
            return DirectoryPathRole.behavior

        # Extension patterns: (.ext only), (.ext1, .ext2), (.ext1/.ext2), etc.
        patterns = [
            # (.json, .yaml) or (.json/.yaml)
            r"\(\.([a-zA-Z0-9]+(?:\s*[,/]\s*\.?[a-zA-Z0-9]+)*)\)",
            r"\(\.([a-zA-Z0-9]+)\s+only\)",  # (.tiff only)
            r"\(([a-zA-Z0-9]+)\s+only\)",  # (tiff only)
            r"\.([a-zA-Z0-9]+)\s+only",  # .tiff only
        ]

        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                ext_string = match.group(1)
                # Split by comma or slash and clean up
                raw_exts = re.split(r"[,/]", ext_string)
                extensions = [f".{ext.strip().lstrip('.')}" for ext in raw_exts if ext.strip()]

                if extensions:
                    return PathBehavior.from_extensions(extensions)

        return None

    @staticmethod
    def _detect_from_parameter_name(param_name: str) -> PathBehavior | None:
        """Detect behavior from parameter name patterns."""
        role = PathNameRole.for_tokens(PathParameterNameTokens.parse(param_name))
        if role is None:
            return None
        return role.behavior


class PathNameRole(metaclass=AutoRegisterMeta):
    """A path-parameter role declared by words in the parameter's name.

    Roles are tried in declaration order; applications add roles by subclassing.
    """

    __registry_key__ = "role_name"
    __key_extractor__ = _role_name
    __skip_if_no_key__ = True

    tokens: ClassVar[frozenset[str]]
    behavior: ClassVar[PathBehavior]

    @classmethod
    def for_tokens(cls, tokens: "PathParameterNameTokens") -> "type[PathNameRole] | None":
        for role in cls.__registry__.values():
            if tokens.contains_any(role.tokens):
                return role
        return None


class DirectoryPathRole(PathNameRole):
    tokens = frozenset({"dir", "directory", "folder"})
    behavior = PathBehavior(
        is_directory=True,
        cache_key=DirectorySelection,
        description="directory",
    )


class FilePathRole(PathNameRole):
    tokens = frozenset({"file", "filepath", "filename"})
    behavior = PathBehavior(
        is_directory=False,
        cache_key=FileSelection,
        description="file",
    )


DEFAULT_PATH_BEHAVIOR = PathBehavior(
    is_directory=False,
    extensions=None,
    cache_key=General,
    description="file or directory",
)


@dataclass(frozen=True, slots=True)
class PathParameterNameTokens:
    """Boundary parse of external parameter names into exact tokens."""

    values: frozenset[str]

    @classmethod
    def parse(cls, param_name: str) -> "PathParameterNameTokens":
        camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", param_name)
        return cls(frozenset(re.findall(r"[a-z0-9]+", camel_split.lower())))

    def contains_any(self, candidates: frozenset[str]) -> bool:
        return bool(self.values.intersection(candidates))


class EnhancedPathWidget(
    PlaceholderStateMixin,
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
        param_info: ParameterInfo | None = None,
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

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        """Preserve a usable editor width beside the browse affordance."""

        layout = self.layout()
        margins = layout.contentsMargins()
        width = (
            self.path_input.sizeHint().width()
            + self.browse_button.minimumSizeHint().width()
            + layout.spacing()
            + margins.left()
            + margins.right()
        )
        height = (
            max(
                self.path_input.minimumSizeHint().height(),
                self.browse_button.minimumSizeHint().height(),
            )
            + margins.top()
            + margins.bottom()
        )
        return QSize(width, height)

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
            initial_dir = str(get_initial_path(self.behavior.cache_key, fallback=Path.home()))

            # Use None as parent to create a clean, top-level dialog
            # This prevents inheriting the dark styling from nested containers
            # and matches the simple appearance of ServiceAdapter dialogs
            parent = None

            if self.behavior.is_directory:
                # Use directory dialog
                selected_path = QFileDialog.getExistingDirectory(
                    parent, self.behavior.title, initial_dir
                )
            else:
                # Use file dialog
                selected_path, _ = QFileDialog.getOpenFileName(
                    parent, self.behavior.title, initial_dir, self.behavior.file_filter
                )

            if selected_path:
                path_obj = Path(selected_path)
                self.set_path(path_obj)
                self.path_changed.emit(str(path_obj))

                # Cache the selection (directory for files, path itself for directories)
                selected_directory = path_obj.parent if path_obj.is_file() else path_obj
                cache_path(self.behavior.cache_key, selected_directory)

        except Exception as e:
            logger.error(f"Failed to open dialog: {e}")
