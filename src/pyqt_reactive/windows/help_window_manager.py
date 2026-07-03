"""PyQt6 help system - reuses Textual TUI help logic and components."""

import inspect
import logging
from typing import Union, Callable, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QTextEdit, QScrollArea, QWidget, QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QGuiApplication

from pyqt_reactive.services.parameter_help_service import (
    NO_PARAMETER_DESCRIPTION as NO_PARAMETER_DESCRIPTION,
    PARAMETER_DESCRIPTION_FORMATTER as PARAMETER_DESCRIPTION_FORMATTER,
    DataclassDocstringResolution as DataclassDocstringResolution,
    DataclassDocstringResolutionKind as DataclassDocstringResolutionKind,
    ParameterDescriptionBody as ParameterDescriptionBody,
    ParameterDescriptionFormatter as ParameterDescriptionFormatter,
    ParameterHelpContent as ParameterHelpContent,
    ParsedParameterDescription as ParsedParameterDescription,
    class_docstring_text as class_docstring_text,
    dataclass_field_description as dataclass_field_description,
    dataclass_parameter_descriptions as dataclass_parameter_descriptions,
    dataclass_type_for_target as dataclass_type_for_target,
    dataclass_type_from_annotation as dataclass_type_from_annotation,
    docstring_info_for_target as docstring_info_for_target,
    is_signature_docstring as is_signature_docstring,
    parameter_description_body as parameter_description_body,
    parameter_description_from_target as parameter_description_from_target,
    parameter_help_content as parameter_help_content,
    parameter_type_display as parameter_type_display,
    parse_parameter_description as parse_parameter_description,
    remove_duplicate_default_sentence as remove_duplicate_default_sentence,
    resolved_parameter_description as resolved_parameter_description,
    source_class_docstring_resolution as source_class_docstring_resolution,
    source_dataclass_type as source_dataclass_type,
    split_default_prefix as split_default_prefix,
    split_docstring_summary as split_docstring_summary,
)
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.theming import StyleSheetGenerator

logger = logging.getLogger(__name__)
HELP_WINDOW_MIN_WIDTH = 420
HELP_WINDOW_MEDIUM_WIDTH = 640
HELP_WINDOW_LARGE_WIDTH = 820
HELP_WINDOW_MAX_WIDTH = 900
HELP_WINDOW_MAX_HEIGHT = 720
HELP_WINDOW_SCREEN_MARGIN = 64
HELP_WINDOW_CONTENT_MARGIN = 4
HELP_WINDOW_CONTENT_SPACING = 4
HELP_WINDOW_DIALOG_MARGIN = 6
HELP_WINDOW_DIALOG_SPACING = 6
ABSENT_VALUE_LABEL = "None"


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


def help_window_width_for_parameter_content(content: ParameterHelpContent) -> int:
    """Choose a readable help-window width from parameter-help content."""
    text_length = len(content.summary) + len(content.description)
    if text_length >= 800:
        return HELP_WINDOW_LARGE_WIDTH
    if text_length >= 180:
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
        layout.setContentsMargins(
            HELP_WINDOW_DIALOG_MARGIN,
            HELP_WINDOW_DIALOG_MARGIN,
            HELP_WINDOW_DIALOG_MARGIN,
            HELP_WINDOW_DIALOG_MARGIN,
        )
        layout.setSpacing(HELP_WINDOW_DIALOG_SPACING)

        # Content area (to be filled by subclasses)
        self.content_area = QScrollArea()
        self.content_area.setWidgetResizable(True)
        self.content_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.content_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.content_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.content_area.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        self.content_area.setStyleSheet("QScrollArea { border: none; padding: 0px; margin: 0px; }")
        layout.addWidget(self.content_area)

        # Close button - styled like other buttons
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(HELP_WINDOW_DIALOG_SPACING)
        button_layout.addStretch()
        
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        self.close_button.setStyleSheet(f"""
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
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def set_content_widget(self, content_widget: QWidget, target_width: int) -> None:
        """Install content and size the dialog to show available content."""
        self.content_area.setWidget(content_widget)
        self.resize_to_content(content_widget, target_width)

    def available_help_bounds(self) -> tuple[int, int]:
        """Return max help-window dimensions bounded by the active screen."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return HELP_WINDOW_MAX_WIDTH, HELP_WINDOW_MAX_HEIGHT

        available = screen.availableGeometry()
        return (
            min(HELP_WINDOW_MAX_WIDTH, available.width() - HELP_WINDOW_SCREEN_MARGIN),
            min(HELP_WINDOW_MAX_HEIGHT, available.height() - HELP_WINDOW_SCREEN_MARGIN),
        )

    def resize_to_content(self, content_widget: QWidget, requested_width: int) -> None:
        """Resize to fit content where possible, bounded by available screen size."""
        max_width, max_height = self.available_help_bounds()
        target_width = min(requested_width, max_width)
        content_width = max(0, target_width - (HELP_WINDOW_DIALOG_MARGIN * 2))

        content_widget.setMinimumWidth(content_width)
        if content_widget.layout() is not None:
            content_widget.layout().activate()
        content_widget.adjustSize()

        dialog_layout = self.layout()
        if dialog_layout is not None:
            dialog_layout.activate()
        button_height = self.close_button.sizeHint().height()
        content_height = content_widget.sizeHint().height()
        chrome_height = button_height + (HELP_WINDOW_DIALOG_MARGIN * 2) + HELP_WINDOW_DIALOG_SPACING
        viewport_height = min(
            content_height + 2,
            max(40, max_height - chrome_height),
        )
        target_height = min(
            max_height,
            max(96, viewport_height + chrome_height + 4),
        )

        self.content_area.setMinimumWidth(content_width)
        self.content_area.setMinimumHeight(viewport_height)
        self.content_area.setMaximumHeight(viewport_height)
        self.setMinimumWidth(target_width)
        self.setMaximumSize(max_width, max_height)
        self.resize(target_width, target_height)


def help_content_label(
    text: str,
    *,
    color_scheme: ColorScheme,
    accent: bool = False,
    title: bool = False,
) -> QLabel:
    """Create compact wrapped help text labels."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    color = color_scheme.text_accent if accent else color_scheme.text_primary
    font_size = 13 if title else 12
    weight = "font-weight: bold;" if title else ""
    label.setStyleSheet(
        "QLabel { "
        f"color: {color_scheme.to_hex(color)}; "
        f"font-size: {font_size}px; "
        f"{weight} "
        "background-color: transparent; "
        "padding: 0px; "
        "margin: 0px; "
        "}"
    )
    return label


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

    def set_help_target(
        self,
        target: Union[Callable, type],
        *,
        title: str,
    ) -> None:
        """Replace displayed callable/class docs without exposing storage details."""
        self.target = target
        self.docstring_info = docstring_info_for_target(target)
        self.setWindowTitle(title)
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
        layout.setContentsMargins(
            HELP_WINDOW_CONTENT_MARGIN,
            HELP_WINDOW_CONTENT_MARGIN,
            HELP_WINDOW_CONTENT_MARGIN,
            HELP_WINDOW_CONTENT_MARGIN,
        )
        layout.setSpacing(HELP_WINDOW_CONTENT_SPACING)

        # Function/class summary
        if self.docstring_info.summary:
            logger.debug(f"🔍 populate_content: summary={self.docstring_info.summary[:50]}...")
            summary_label = help_content_label(
                self.docstring_info.summary,
                color_scheme=self.color_scheme,
                title=True,
            )
            layout.addWidget(summary_label)
            logger.info(f"🔍 Added summary_label with style: {summary_label.styleSheet()}")

        # Full description
        if self.docstring_info.description:
            logger.debug(f"🔍 populate_content: description={self.docstring_info.description[:50]}...")
            desc_label = help_content_label(
                self.docstring_info.description,
                color_scheme=self.color_scheme,
            )
            layout.addWidget(desc_label)
            
        # Parameters section
        if self.docstring_info.parameters:
            params_label = help_content_label(
                "Parameters:",
                color_scheme=self.color_scheme,
                accent=True,
                title=True,
            )
            layout.addWidget(params_label)

            for param_name, param_desc in self.docstring_info.parameters.items():
                # Parameter name
                name_label = help_content_label(
                    f"• {param_name}",
                    color_scheme=self.color_scheme,
                )
                layout.addWidget(name_label)

                # Parameter description
                if param_desc:
                    desc_label = help_content_label(
                        param_desc,
                        color_scheme=self.color_scheme,
                    )
                    layout.addWidget(desc_label)
                
        # Returns section
        if self.docstring_info.returns:
            returns_label = help_content_label(
                "Returns:",
                color_scheme=self.color_scheme,
                accent=True,
                title=True,
            )
            layout.addWidget(returns_label)

            returns_desc = help_content_label(
                self.docstring_info.returns,
                color_scheme=self.color_scheme,
            )
            layout.addWidget(returns_desc)

        # Examples section
        if self.docstring_info.examples:
            examples_label = help_content_label(
                "Examples:",
                color_scheme=self.color_scheme,
                accent=True,
                title=True,
            )
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
            
        logger.info(f"🔍 populate_content() COMPLETED - content_widget children: {content_widget.children()}")
        logger.info(f"🔍 Window stylesheet: {self.styleSheet()[:200]}...")

        self.set_content_widget(
            content_widget,
            help_window_width_for_content(self.docstring_info),
        )


class ParameterHelpWindow(BaseHelpWindow):
    """Help window for one parameter or dataclass field."""

    def __init__(
        self,
        content: ParameterHelpContent,
        title: str = "Parameter",
        color_scheme: Optional[ColorScheme] = None,
        parent=None,
    ):
        self.content = content
        super().__init__(title, color_scheme, parent)
        self.populate_content()

    def set_parameter_content(
        self,
        content: ParameterHelpContent,
        *,
        title: str,
    ) -> None:
        """Replace displayed parameter content without changing renderer type."""
        self.content = content
        self.setWindowTitle(title)
        self.populate_content()

    def populate_content(self) -> None:
        """Populate compact parameter help content."""
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(
            HELP_WINDOW_CONTENT_MARGIN,
            HELP_WINDOW_CONTENT_MARGIN,
            HELP_WINDOW_CONTENT_MARGIN,
            HELP_WINDOW_CONTENT_MARGIN,
        )
        layout.setSpacing(HELP_WINDOW_CONTENT_SPACING)

        if self.content.summary:
            layout.addWidget(
                help_content_label(
                    self.content.summary,
                    color_scheme=self.color_scheme,
                    title=True,
                )
            )
        if self.content.description:
            layout.addWidget(
                help_content_label(
                    self.content.description,
                    color_scheme=self.color_scheme,
                )
            )

        self.set_content_widget(
            content_widget,
            help_window_width_for_parameter_content(self.content),
        )


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
                    if (
                        not cls._help_window.isHidden()
                        and isinstance(cls._help_window, DocstringHelpWindow)
                    ):
                        logger.info(f"🔍 Reusing existing help window")
                        if title is None:
                            window_title = f"Help: {help_target_display_name(target)}"
                        else:
                            window_title = title
                        cls._help_window.set_help_target(target, title=window_title)
                        cls._position_window_near_cursor(cls._help_window)
                        cls._help_window.raise_()
                        cls._help_window.activateWindow()
                        return
                    if not cls._help_window.isHidden():
                        cls._help_window.close()
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
        """Show help for a parameter using parameter-help content directly."""
        import logging
        logger = logging.getLogger(__name__)

        try:
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

            if param_desc:
                log_description = param_desc[:50]
            else:
                log_description = ABSENT_VALUE_LABEL
            logger.debug(f"🔍 show_parameter_help: param_name={param_name}, param_description={log_description}")

            # Check if existing window is still valid
            if isinstance(cls._help_window, QDialog):
                try:
                    if (
                        not cls._help_window.isHidden()
                        and isinstance(cls._help_window, ParameterHelpWindow)
                    ):
                        cls._help_window.set_parameter_content(
                            help_content,
                            title=f"Parameter: {param_name}",
                        )
                        cls._position_window_near_cursor(cls._help_window)
                        cls._help_window.raise_()
                        cls._help_window.activateWindow()
                        return
                    if not cls._help_window.isHidden():
                        cls._help_window.close()
                except RuntimeError:
                    # Window was deleted, clear reference
                    cls._help_window = None

            cls._help_window = ParameterHelpWindow(
                help_content,
                title=f"Parameter: {param_name}",
                parent=parent,
            )
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
