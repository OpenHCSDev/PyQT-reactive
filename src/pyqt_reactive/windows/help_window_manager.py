"""PyQt6 help system - reuses Textual TUI help logic and components."""

import inspect
import logging
import ast
import re
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Annotated, Union, Callable, Optional, get_args, get_origin
from types import UnionType
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QTextEdit, QScrollArea, QWidget, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QGuiApplication

# REUSE the actual working Textual TUI help components
from python_introspect import DocstringExtractor, DocstringInfo, UnifiedParameterAnalyzer
from objectstate.lazy_factory import get_base_type_for_lazy, is_lazy_dataclass
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.theming import StyleSheetGenerator

logger = logging.getLogger(__name__)
NO_PARAMETER_DESCRIPTION = "No description available"
HELP_WINDOW_MIN_WIDTH = 420
HELP_WINDOW_MEDIUM_WIDTH = 640
HELP_WINDOW_LARGE_WIDTH = 820
HELP_WINDOW_MAX_WIDTH = 900
HELP_WINDOW_MAX_HEIGHT = 720
HELP_WINDOW_SCREEN_MARGIN = 64
ABSENT_VALUE_LABEL = "None"


@dataclass(frozen=True, slots=True)
class ParameterHelpContent:
    """Display-ready content for one parameter help popup."""

    summary: str
    description: str


@dataclass(frozen=True, slots=True)
class ParsedParameterDescription:
    """Structured projection of the generated parameter documentation prefix."""

    type_name: str | None
    default_value: str | None
    description: str


@dataclass(frozen=True, slots=True)
class ParameterDescriptionBody:
    """Formatted body fields for one parsed parameter description."""

    setting_name: str | None
    description: str


class DataclassDocstringResolutionKind(Enum):
    """Provenance for source-authored dataclass docstring resolution."""

    FOUND = "found"
    CLASS_NOT_FOUND = "class_not_found"
    DOCSTRING_MISSING = "docstring_missing"


@dataclass(frozen=True, slots=True)
class DataclassDocstringResolution:
    """Result of resolving a source-authored dataclass docstring."""

    kind: DataclassDocstringResolutionKind
    docstring: str | None


@dataclass(frozen=True, slots=True)
class ParameterDescriptionFormatter:
    """Display formatter for compact parameter help prose."""

    def strip_rst_directives(self, text: str) -> str:
        """Remove inline RST directives that are not useful in a compact popup."""
        text = re.sub(r"\s*\.\. image:: \{[^}]+\}", "", text)
        text = re.sub(r"\s*\.\. _\w+:\s+\S+", "", text)
        return text.strip()

    def format_inline_list_markers(self, text: str) -> str:
        """Give flattened CellProfiler list markers paragraph breaks."""
        text = re.sub(r"\s+-\s+(\{[^}]+\}:)", r"\n\n- \1", text)
        text = re.sub(r"\s+References\s+-\s+", "\n\nReferences\n\n- ", text)
        text = text.replace(" NOTE ", "\n\nNOTE ")
        return text.strip()

    def format_body(self, text: str) -> str:
        """Return display-ready body prose for parameter help."""
        return self.format_inline_list_markers(self.strip_rst_directives(text))


PARAMETER_DESCRIPTION_FORMATTER = ParameterDescriptionFormatter()


def dataclass_type_for_target(target: Union[Callable, type, None]) -> type | None:
    """Return the dataclass type represented by a help target."""
    if target is None:
        return None
    if inspect.isclass(target) and is_dataclass(target):
        return target
    target_type = type(target)
    if is_dataclass(target_type):
        return target_type
    return None


def source_dataclass_type(dataclass_type: type) -> type:
    """Return the source-authored dataclass for generated lazy dataclass types."""
    if is_lazy_dataclass(dataclass_type):
        base_type = get_base_type_for_lazy(dataclass_type)
        if base_type is None:
            raise RuntimeError(
                f"Lazy dataclass {dataclass_type.__qualname__} is missing its "
                "registered source dataclass type."
            )
        if not is_dataclass(base_type):
            raise RuntimeError(
                f"Lazy dataclass {dataclass_type.__qualname__} resolves to "
                f"non-dataclass source type {base_type!r}."
            )
        return base_type

    return dataclass_type


def source_class_docstring_resolution(dataclass_type: type) -> DataclassDocstringResolution:
    """Extract the authored class docstring instead of dataclass' rendered signature."""
    source_type = source_dataclass_type(dataclass_type)
    source = inspect.getsource(source_type)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == source_type.__name__:
            docstring = ast.get_docstring(node)
            if docstring is None:
                return DataclassDocstringResolution(
                    kind=DataclassDocstringResolutionKind.DOCSTRING_MISSING,
                    docstring=None,
                )
            return DataclassDocstringResolution(
                kind=DataclassDocstringResolutionKind.FOUND,
                docstring=docstring,
            )
    return DataclassDocstringResolution(
        kind=DataclassDocstringResolutionKind.CLASS_NOT_FOUND,
        docstring=None,
    )


def is_signature_docstring(text: str | None, type_name: str) -> bool:
    """Return whether a dataclass docstring is just the generated constructor signature."""
    if text is None:
        return False
    return text.lstrip().startswith(f"{type_name}(")


def class_docstring_text(dataclass_type: type) -> str | None:
    """Return a human-authored dataclass docstring when one is available."""
    source_type = source_dataclass_type(dataclass_type)
    source_docstring = source_class_docstring_resolution(source_type)
    if source_docstring.kind is DataclassDocstringResolutionKind.FOUND:
        return source_docstring.docstring
    logger.debug(
        "Dataclass source docstring resolution for %s ended with %s.",
        source_type.__qualname__,
        source_docstring.kind.value,
    )

    inspected_docstring = inspect.getdoc(source_type)
    if is_signature_docstring(inspected_docstring, source_type.__name__):
        return None
    return inspected_docstring


def split_docstring_summary(docstring: str | None, fallback: str) -> tuple[str, str | None]:
    """Split a docstring into summary and optional remaining description."""
    if not docstring:
        return fallback, None
    lines = docstring.strip().splitlines()
    if not lines:
        summary = fallback
    else:
        summary = lines[0].strip()
    description = "\n".join(line.rstrip() for line in lines[1:]).strip()
    if description == "":
        return summary, None
    return summary, description


def dataclass_type_from_annotation(annotation) -> type | None:
    """Return a dataclass type represented by a field annotation."""
    if inspect.isclass(annotation) and is_dataclass(annotation):
        return annotation

    origin = get_origin(annotation)
    if origin is Annotated:
        annotated_args = get_args(annotation)
        if not annotated_args:
            return None
        return dataclass_type_from_annotation(annotated_args[0])

    if origin in (Union, UnionType):
        dataclass_args = tuple(
            arg for arg in get_args(annotation)
            if inspect.isclass(arg) and is_dataclass(arg)
        )
        if len(dataclass_args) == 1:
            return dataclass_args[0]
    return None


def dataclass_field_description(description: str | None, annotation) -> str | None:
    """Return displayable docs for one dataclass field."""
    field_type = dataclass_type_from_annotation(annotation)
    if description and (
        field_type is None
        or not is_signature_docstring(description, field_type.__name__)
    ):
        return description

    if field_type is None:
        return description

    class_docstring = class_docstring_text(field_type)
    summary, description_body = split_docstring_summary(
        class_docstring,
        f"{source_dataclass_type(field_type).__name__} configuration fields.",
    )
    if description_body:
        return f"{summary}\n\n{description_body}"
    return summary


def dataclass_parameter_descriptions(dataclass_type: type) -> dict[str, str]:
    """Return field descriptions for a dataclass using the shared introspection path."""
    analyzed = UnifiedParameterAnalyzer.analyze(dataclass_type)
    dataclass_fields = {field.name: field for field in fields(dataclass_type)}
    descriptions: dict[str, str] = {}
    for name, info in analyzed.items():
        if name in dataclass_fields:
            annotation = dataclass_fields[name].type
        else:
            annotation = None
        description = dataclass_field_description(info.description, annotation)
        if description:
            descriptions[name] = description
    return descriptions


def docstring_info_for_target(target: Union[Callable, type]) -> DocstringInfo:
    """Return help-window documentation, using field docs for dataclass targets."""
    dataclass_type = dataclass_type_for_target(target)
    if dataclass_type is None:
        return DocstringExtractor.extract(target)

    source_type = source_dataclass_type(dataclass_type)
    summary, description = split_docstring_summary(
        class_docstring_text(dataclass_type),
        source_type.__name__,
    )
    return DocstringInfo(
        summary=summary,
        description=description,
        parameters=dataclass_parameter_descriptions(dataclass_type),
        returns="",
        examples="",
    )


def parameter_description_from_target(
    help_target: Union[Callable, type, None],
    param_name: str,
) -> Optional[str]:
    """Return parsed documentation for one parameter from a callable/class target."""
    if help_target is None:
        return None

    dataclass_type = dataclass_type_for_target(help_target)
    if dataclass_type is not None:
        descriptions = dataclass_parameter_descriptions(dataclass_type)
        if param_name not in descriptions:
            return None
        return descriptions[param_name]

    docstring_info = DocstringExtractor.extract(help_target)
    if not docstring_info.parameters:
        return None
    if param_name not in docstring_info.parameters:
        return None
    return docstring_info.parameters[param_name]


def resolved_parameter_description(
    *,
    help_target: Union[Callable, type, None],
    param_name: str,
    widget_description: str,
) -> str:
    """Resolve parameter help text from target docs, then explicit widget metadata."""
    target_description = parameter_description_from_target(help_target, param_name)
    if target_description:
        return target_description
    if widget_description:
        return widget_description
    return NO_PARAMETER_DESCRIPTION


def parameter_type_display(param_type: type | None) -> str:
    """Return the compact type label used by parameter help."""
    if param_type is None:
        return ""
    if isinstance(param_type, type):
        return f" ({param_type.__name__})"
    return f" ({param_type})"


def split_default_prefix(text: str) -> tuple[str, str]:
    """Split a rendered default literal from the following sentence body."""
    sentence_separator = ". "
    separator_index = text.find(sentence_separator)
    if separator_index >= 0:
        return (
            text[:separator_index],
            text[separator_index + len(sentence_separator) :],
        )
    return text.rstrip("."), ""


def parse_parameter_description(description: str) -> ParsedParameterDescription:
    """Parse the type/default prefix emitted by DocstringExtractor parameter docs."""
    if not description.startswith("'"):
        unquoted_match = re.match(
            r"^(?P<type>[^.;]+);\s+default\s+(?P<default_and_body>.*)$",
            description,
        )
        if unquoted_match is not None:
            default_value, body = split_default_prefix(
                unquoted_match.group("default_and_body"),
            )
            return ParsedParameterDescription(
                type_name=unquoted_match.group("type").strip(),
                default_value=default_value.strip(),
                description=body.strip(),
            )
        return ParsedParameterDescription(
            type_name=None,
            default_value=None,
            description=description,
        )

    closing_quote_index = description.find("'", 1)
    if closing_quote_index < 0:
        return ParsedParameterDescription(
            type_name=None,
            default_value=None,
            description=description,
        )

    type_name = description[1:closing_quote_index]
    remainder = description[closing_quote_index + 1 :].lstrip()
    if remainder.startswith("."):
        remainder = remainder[1:].lstrip()

    default_value = None
    default_prefix = "; default "
    if remainder.startswith(default_prefix):
        default_value, remainder = split_default_prefix(remainder[len(default_prefix) :])

    return ParsedParameterDescription(
        type_name=type_name,
        default_value=default_value,
        description=remainder,
    )


def parameter_description_body(description: str) -> ParameterDescriptionBody:
    """Split CellProfiler setting metadata from the prose body."""
    setting_prefix = "CellProfiler setting '"
    if not description.startswith(setting_prefix):
        return ParameterDescriptionBody(
            setting_name=None,
            description=PARAMETER_DESCRIPTION_FORMATTER.format_body(description),
        )

    setting_start = len(setting_prefix)
    setting_end = description.find("'", setting_start)
    if setting_end < 0:
        return ParameterDescriptionBody(
            setting_name=None,
            description=PARAMETER_DESCRIPTION_FORMATTER.format_body(description),
        )

    setting_name = description[setting_start:setting_end]
    remainder = description[setting_end + 1 :].lstrip()
    if remainder.startswith("."):
        remainder = remainder[1:].lstrip()
    return ParameterDescriptionBody(
        setting_name=setting_name,
        description=PARAMETER_DESCRIPTION_FORMATTER.format_body(remainder),
    )


def _default_values_match(left: str, right: str) -> bool:
    """Return whether two rendered default literals describe the same value."""
    if left == right:
        return True
    numeric_pattern = r"[-+]?\d+(?:\.\d+)?"
    if re.fullmatch(numeric_pattern, left) and re.fullmatch(numeric_pattern, right):
        return float(left) == float(right)
    return False


def remove_duplicate_default_sentence(description: str, default_value: str | None) -> str:
    """Remove body-level default sentence already shown in the default section."""
    if default_value is None:
        return description

    def replacement(match: re.Match[str]) -> str:
        rendered_default = match.group("value").strip()
        if _default_values_match(default_value, rendered_default):
            return ""
        return match.group(0)

    return re.sub(
        r"(?:\s+|^)Default is (?P<value>[-+]?\d+(?:\.\d+)?|[^.]+)\.",
        replacement,
        description,
    ).strip()


def parameter_help_content(
    *,
    param_name: str,
    param_type: type | None,
    description: str,
) -> ParameterHelpContent:
    """Build compact popup content without leaking raw Python annotations."""
    parsed = parse_parameter_description(description)
    type_str = f" ({parsed.type_name})" if parsed.type_name else parameter_type_display(param_type)
    body = parameter_description_body(parsed.description)
    lines: list[str] = []
    if parsed.default_value:
        lines.append(f"Default: {parsed.default_value}")
    if body.setting_name:
        lines.append(f"CellProfiler setting: {body.setting_name}")
    body_description = remove_duplicate_default_sentence(
        body.description,
        parsed.default_value,
    )
    if body_description:
        lines.append(body_description)
    return ParameterHelpContent(
        summary=f"• {param_name}{type_str}",
        description="\n\n".join(lines) if lines else NO_PARAMETER_DESCRIPTION,
    )


def help_target_display_name(target: Union[Callable, type]) -> str:
    """Return the display name for a documented function/class target."""
    if inspect.isclass(target) or inspect.isfunction(target) or inspect.ismethod(target):
        return target.__name__
    return type(target).__name__


def optional_text_length(value: str | None) -> int:
    """Return text length for an optional docstring section."""
    if value is None:
        return 0
    return len(value)


def total_docstring_text_length(docstring_info) -> int:
    """Return approximate rendered text length for help-window sizing."""
    total = optional_text_length(docstring_info.summary)
    total += optional_text_length(docstring_info.description)
    total += optional_text_length(docstring_info.returns)
    total += optional_text_length(docstring_info.examples)
    if docstring_info.parameters:
        total += sum(
            len(name) + optional_text_length(description)
            for name, description in docstring_info.parameters.items()
        )
    return total


def help_window_width_for_content(docstring_info) -> int:
    """Choose a readable help-window width from rendered content volume."""
    text_length = total_docstring_text_length(docstring_info)
    if text_length >= 1200:
        return HELP_WINDOW_LARGE_WIDTH
    if text_length >= 300:
        return HELP_WINDOW_MEDIUM_WIDTH
    return HELP_WINDOW_MIN_WIDTH


class BaseHelpWindow(QDialog):
    """Base class for all PyQt6 help windows - reuses Textual TUI help logic."""
    
    def __init__(self, title: str = "Help", color_scheme: Optional[ColorScheme] = None, parent=None):
        super().__init__(parent)

        # Initialize color scheme and style generator
        self.color_scheme = color_scheme or ColorScheme()
        self.style_generator = StyleSheetGenerator(self.color_scheme)

        self.setWindowTitle(title)
        self.setModal(False)  # Allow interaction with main window

        # Setup UI
        self.setup_ui()

        # Apply centralized styling
        self.setStyleSheet(self.style_generator.generate_dialog_style())
        
    def setup_ui(self):
        """Setup the base help window UI."""
        layout = QVBoxLayout(self)
        
        # Content area (to be filled by subclasses)
        self.content_area = QScrollArea()
        self.content_area.setWidgetResizable(True)
        self.content_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.content_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self.content_area)
        
        # Close button - styled like other buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.button_normal_bg)};
                color: {self.color_scheme.to_hex(self.color_scheme.button_text)};
                border: none;
                padding: 6px 12px;
                border-radius: 3px;
                font-weight: normal;
            }}
            QPushButton:hover {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.button_hover_bg)};
            }}
            QPushButton:pressed {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.button_pressed_bg)};
            }}
        """)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)


class DocstringHelpWindow(BaseHelpWindow):
    """Help window for functions and classes - reuses Textual TUI DocstringExtractor."""
    
    def __init__(self, target: Union[Callable, type], title: Optional[str] = None,
                 color_scheme: Optional[ColorScheme] = None, parent=None):
        self.target = target

        # Reuse Textual TUI docstring parsing for callables, but use
        # source-aware field docs for dataclass configuration targets.
        self.docstring_info = docstring_info_for_target(target)

        # Generate title from target if not provided
        if title is None:
            title = f"Help: {help_target_display_name(target)}"

        super().__init__(title, color_scheme, parent)
        self.populate_content()
        
    def populate_content(self):
        """Populate the help content with minimal styling."""
        import logging
        logger = logging.getLogger(__name__)

        logger.info(f"🔍 populate_content() CALLED")
        logger.info(f"🔍 docstring_info.summary: {bool(self.docstring_info.summary)}")
        logger.info(f"🔍 docstring_info.description: {bool(self.docstring_info.description)}")
        logger.info(f"🔍 docstring_info.parameters: {bool(self.docstring_info.parameters)}")
        logger.info(f"🔍 docstring_info.returns: {bool(self.docstring_info.returns)}")
        logger.info(f"🔍 docstring_info.examples: {bool(self.docstring_info.examples)}")
        parent_widget = self.parent()
        if parent_widget is None:
            parent_type_name = ABSENT_VALUE_LABEL
        else:
            parent_type_name = type(parent_widget).__name__
        logger.info(f"🔍 Window parent: {parent_widget}, type: {parent_type_name}")
        logger.info(f"🔍 Color scheme: {self.color_scheme}")

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        # Function/class summary
        if self.docstring_info.summary:
            logger.debug(f"🔍 populate_content: summary={self.docstring_info.summary[:50]}...")
            summary_label = QLabel(self.docstring_info.summary)
            summary_label.setWordWrap(True)
            summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            summary_label.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_primary)}; font-size: 12px; background-color: {self.color_scheme.to_hex(self.color_scheme.panel_bg)}; padding: 5px;")
            layout.addWidget(summary_label)
            logger.info(f"🔍 Added summary_label with style: {summary_label.styleSheet()}")

        # Full description
        if self.docstring_info.description:
            logger.debug(f"🔍 populate_content: description={self.docstring_info.description[:50]}...")
            desc_label = QLabel(self.docstring_info.description)
            desc_label.setWordWrap(True)
            desc_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            desc_label.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_primary)}; font-size: 12px; background-color: {self.color_scheme.to_hex(self.color_scheme.panel_bg)}; padding: 5px;")
            layout.addWidget(desc_label)
            
        # Parameters section
        if self.docstring_info.parameters:
            params_label = QLabel("Parameters:")
            params_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            params_label.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_accent)}; font-size: 14px; font-weight: bold; margin-top: 8px;")
            layout.addWidget(params_label)

            for param_name, param_desc in self.docstring_info.parameters.items():
                # Parameter name
                name_label = QLabel(f"• {param_name}")
                name_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                name_label.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_primary)}; font-size: 12px; margin-left: 5px; margin-top: 3px;")
                layout.addWidget(name_label)

                # Parameter description
                if param_desc:
                    desc_label = QLabel(param_desc)
                    desc_label.setWordWrap(True)
                    desc_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                    desc_label.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_primary)}; font-size: 12px; margin-left: 20px;")
                    layout.addWidget(desc_label)
                
        # Returns section
        if self.docstring_info.returns:
            returns_label = QLabel("Returns:")
            returns_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            returns_label.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_accent)}; font-size: 14px; font-weight: bold; margin-top: 8px;")
            layout.addWidget(returns_label)

            returns_desc = QLabel(self.docstring_info.returns)
            returns_desc.setWordWrap(True)
            returns_desc.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            returns_desc.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_primary)}; font-size: 12px; margin-left: 5px;")
            layout.addWidget(returns_desc)
            
        # Examples section
        if self.docstring_info.examples:
            examples_label = QLabel("Examples:")
            examples_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            examples_label.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_accent)}; font-size: 14px; font-weight: bold; margin-top: 8px;")
            layout.addWidget(examples_label)

            examples_text = QTextEdit()
            examples_text.setPlainText(self.docstring_info.examples)
            examples_text.setReadOnly(True)
            examples_text.setMaximumHeight(150)
            examples_text.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            examples_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: transparent;
                    color: {self.color_scheme.to_hex(self.color_scheme.text_primary)};
                    border: none;
                    font-family: monospace;
                    font-size: 11px;
                }}
                QTextEdit:hover {{
                    background-color: transparent;
                }}
            """)
            layout.addWidget(examples_text)
            
        layout.addStretch()
        self.content_area.setWidget(content_widget)
        
        logger.info(f"🔍 populate_content() COMPLETED - content_widget children: {content_widget.children()}")
        logger.info(f"🔍 Window stylesheet: {self.styleSheet()[:200]}...")

        # Auto-size to content
        self.resize_to_content(content_widget)

    def resize_to_content(self, content_widget: QWidget) -> None:
        """Resize to fit content where possible, bounded by available screen size."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            available = None
        else:
            available = screen.availableGeometry()
        if available is None:
            max_width = HELP_WINDOW_MAX_WIDTH
            max_height = HELP_WINDOW_MAX_HEIGHT
        else:
            max_width = min(HELP_WINDOW_MAX_WIDTH, available.width() - HELP_WINDOW_SCREEN_MARGIN)
            max_height = min(HELP_WINDOW_MAX_HEIGHT, available.height() - HELP_WINDOW_SCREEN_MARGIN)

        target_width = min(help_window_width_for_content(self.docstring_info), max_width)
        content_widget.setMinimumWidth(max(0, target_width - 40))
        content_widget.layout().activate()
        content_widget.adjustSize()

        self.setMaximumSize(max_width, max_height)
        self.adjustSize()
        target_height = min(max_height, max(180, self.sizeHint().height()))
        self.resize(target_width, target_height)


class HelpWindowManager:
    """PyQt6 help window manager - unified window for all help content."""

    # Class-level window reference for singleton behavior
    _help_window = None

    @classmethod
    def _position_window_near_cursor(cls, window: QDialog) -> None:
        """Position help window near the mouse cursor within screen bounds."""
        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        window.adjustSize()
        size = window.size()

        x = cursor_pos.x() - size.width() - 16
        y = cursor_pos.y() - size.height() - 16

        if x < available.left():
            x = available.left()
        if y < available.top():
            y = available.top()

        if x + size.width() > available.right():
            x = max(available.left(), available.right() - size.width())
        if y + size.height() > available.bottom():
            y = max(available.top(), available.bottom() - size.height())

        window.move(x, y)

    @classmethod
    def show_docstring_help(cls, target: Union[Callable, type], title: Optional[str] = None, parent=None):
        """Show help for a function or class - reuses Textual TUI extraction logic."""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔍 show_docstring_help() CALLED - target={target}, title={title}")
        if parent is None:
            parent_type_name = ABSENT_VALUE_LABEL
        else:
            parent_type_name = type(parent).__name__
        logger.info(f"🔍 show_docstring_help() parent={parent}, parent_type={parent_type_name}")
        
        try:
            # Check if existing window is still valid
            if isinstance(cls._help_window, QDialog):
                try:
                    if not cls._help_window.isHidden():
                        logger.info(f"🔍 Reusing existing help window")
                        cls._help_window.target = target
                        cls._help_window.docstring_info = docstring_info_for_target(target)
                        if title is None:
                            window_title = f"Help: {help_target_display_name(target)}"
                        else:
                            window_title = title
                        cls._help_window.setWindowTitle(window_title)
                        cls._help_window.populate_content()
                        cls._position_window_near_cursor(cls._help_window)
                        cls._help_window.raise_()
                        cls._help_window.activateWindow()
                        return
                except RuntimeError:
                    # Window was deleted, clear reference
                    cls._help_window = None

            # Create new window
            logger.info(f"🔍 Creating new DocstringHelpWindow")
            cls._help_window = DocstringHelpWindow(target, title=title, parent=parent)
            logger.info(f"🔍 DocstringHelpWindow created, calling show()")
            cls._help_window.show()
            cls._position_window_near_cursor(cls._help_window)
            logger.info(f"🔍 DocstringHelpWindow shown")

        except Exception as e:
            logger.error(f"Failed to show docstring help: {e}")
            QMessageBox.warning(parent, "Help Error", f"Failed to show help: {e}")

    @classmethod
    def show_parameter_help(
        cls,
        param_name: str,
        param_description: str,
        param_type: type = None,
        *,
        help_target: Union[Callable, type, None] = None,
        parent=None,
    ):
        """Show help for a parameter - creates a fake docstring object and uses DocstringHelpWindow."""
        import logging
        logger = logging.getLogger(__name__)

        try:
            # Create a fake docstring info object for the parameter
            from dataclasses import dataclass

            @dataclass
            class FakeDocstringInfo:
                summary: str = ""
                description: str = ""
                parameters: dict = None
                returns: str = ""
                examples: str = ""

            # Build parameter display - combine everything into summary to create single QLabel
            param_desc = resolved_parameter_description(
                help_target=help_target,
                param_name=param_name,
                widget_description=param_description,
            )
            help_content = parameter_help_content(
                param_name=param_name,
                param_type=param_type,
                description=param_desc,
            )
            fake_info = FakeDocstringInfo(
                summary=help_content.summary,
                description=help_content.description,
                parameters={},
                returns="",
                examples=""
            )

            if param_desc:
                log_description = param_desc[:50]
            else:
                log_description = ABSENT_VALUE_LABEL
            logger.debug(f"🔍 show_parameter_help: param_name={param_name}, param_description={log_description}")

            # Check if existing window is still valid
            if isinstance(cls._help_window, QDialog):
                try:
                    if not cls._help_window.isHidden():
                        cls._help_window.docstring_info = fake_info
                        cls._help_window.setWindowTitle(f"Parameter: {param_name}")
                        cls._help_window.populate_content()
                        cls._position_window_near_cursor(cls._help_window)
                        cls._help_window.raise_()
                        cls._help_window.activateWindow()
                        return
                except RuntimeError:
                    # Window was deleted, clear reference
                    cls._help_window = None

            # Create new window with fake target
            class FakeTarget:
                __name__ = param_name

            cls._help_window = DocstringHelpWindow(FakeTarget, title=f"Parameter: {param_name}", parent=parent)
            cls._help_window.docstring_info = fake_info
            cls._help_window.populate_content()
            cls._help_window.show()
            cls._position_window_near_cursor(cls._help_window)

        except Exception as e:
            logger.error(f"Failed to show parameter help: {e}")
            QMessageBox.warning(parent, "Help Error", f"Failed to show help: {e}")


class HelpableWidget:
    """Mixin class to add help functionality to PyQt6 widgets - mirrors Textual TUI."""
    
    def show_function_help(self, target: Union[Callable, type]) -> None:
        """Show help window for a function or class."""
        HelpWindowManager.show_docstring_help(target, parent=self)
        
    def show_parameter_help(self, param_name: str, param_description: str, param_type: type = None) -> None:
        """Show help window for a parameter."""
        HelpWindowManager.show_parameter_help(param_name, param_description, param_type, parent=self)
