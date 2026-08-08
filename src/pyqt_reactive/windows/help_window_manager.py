"""PyQt6 help windows backed by the shared rich-document renderer."""

import inspect
import logging
from collections.abc import Callable

from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from pyqt_reactive.services.help_document import HelpDocument
from pyqt_reactive.services.parameter_help_service import (
    ParameterHelpContent,
    docstring_info_for_target,
    parameter_help_content,
    resolved_parameter_description,
)
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.help_document_browser import HelpDocumentBrowser

logger = logging.getLogger(__name__)
HELP_WINDOW_MIN_WIDTH = 420
HELP_WINDOW_MEDIUM_WIDTH = 640
HELP_WINDOW_LARGE_WIDTH = 820
HELP_WINDOW_MAX_WIDTH = 900
HELP_WINDOW_MAX_HEIGHT = 720
HELP_WINDOW_SCREEN_MARGIN = 64
HELP_WINDOW_DIALOG_MARGIN = 6
HELP_WINDOW_DIALOG_SPACING = 6


def help_target_display_name(target: Callable | type) -> str:
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
    """Base dialog lifecycle for all shared rich help documents."""

    def __init__(
        self,
        title: str = "Help",
        color_scheme: ColorScheme | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.color_scheme = color_scheme or ColorScheme()

        self.setWindowTitle(title)
        self.setModal(False)  # Allow interaction with main window

        # Setup UI
        self.setup_ui()

        # Apply centralized styling
        self.setStyleSheet(self.color_scheme.styles.generate_dialog_style())

    def setup_ui(self) -> None:
        """Setup the base help window UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            HELP_WINDOW_DIALOG_MARGIN,
            HELP_WINDOW_DIALOG_MARGIN,
            HELP_WINDOW_DIALOG_MARGIN,
            HELP_WINDOW_DIALOG_MARGIN,
        )
        layout.setSpacing(HELP_WINDOW_DIALOG_SPACING)

        self.content_area = HelpDocumentBrowser(
            color_scheme=self.color_scheme,
            parent=self,
        )
        layout.addWidget(self.content_area, 1)

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

    def set_help_document(
        self,
        document: HelpDocument,
        *,
        target_width: int,
    ) -> None:
        """Install a typed help document and size its scrollable viewport."""
        self.content_area.set_help_document(document)
        self.resize_to_document(target_width)

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

    def resize_to_document(
        self,
        requested_width: int,
    ) -> None:
        """Resize around readable bounds while retaining scrolling for long docs."""
        max_width, max_height = self.available_help_bounds()
        target_width = min(requested_width, max_width)
        content_width = max(0, target_width - (HELP_WINDOW_DIALOG_MARGIN * 2))
        button_height = self.close_button.sizeHint().height()
        chrome_height = button_height + (HELP_WINDOW_DIALOG_MARGIN * 2) + HELP_WINDOW_DIALOG_SPACING
        content_height = max(
            112,
            min(
                self.content_area.document_height_for_width(content_width),
                540,
            ),
        )
        viewport_height = min(
            content_height,
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


class DocstringHelpWindow(BaseHelpWindow):
    """Help window for functions and classes."""

    def __init__(
        self,
        target: Callable | type,
        title: str | None = None,
        color_scheme: ColorScheme | None = None,
        parent=None,
    ) -> None:
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
        target: Callable | type,
        *,
        title: str,
    ) -> None:
        """Replace displayed callable/class docs without exposing storage details."""
        self.target = target
        self.docstring_info = docstring_info_for_target(target)
        self.setWindowTitle(title)
        self.populate_content()

    def populate_content(self) -> None:
        """Project introspection through the shared rich-document renderer."""
        self.set_help_document(
            HelpDocument.from_docstring_info(self.docstring_info),
            target_width=help_window_width_for_content(self.docstring_info),
        )


class ParameterHelpWindow(BaseHelpWindow):
    """Help window for one parameter or dataclass field."""

    def __init__(
        self,
        content: ParameterHelpContent,
        title: str = "Parameter",
        color_scheme: ColorScheme | None = None,
        parent=None,
    ) -> None:
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
        """Project parameter content through the shared rich-document renderer."""
        self.set_help_document(
            HelpDocument.from_parameter_content(
                summary=self.content.summary,
                description=self.content.description,
            ),
            target_width=help_window_width_for_parameter_content(self.content),
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
    def show_docstring_help(
        cls,
        target: Callable | type,
        title: str | None = None,
        parent=None,
    ) -> None:
        """Show or refresh help for a function or class."""
        logger.debug("Showing docstring help for %r", target)
        try:
            # Check if existing window is still valid
            if isinstance(cls._help_window, QDialog):
                try:
                    if (
                        not cls._help_window.isHidden()
                        and isinstance(cls._help_window, DocstringHelpWindow)
                    ):
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
            cls._help_window = DocstringHelpWindow(target, title=title, parent=parent)
            cls._help_window.show()
            cls._position_window_near_cursor(cls._help_window)

        except Exception as error:
            logger.exception("Failed to show docstring help")
            QMessageBox.warning(parent, "Help Error", f"Failed to show help: {error}")

    @classmethod
    def show_parameter_help(
        cls,
        param_name: str,
        param_description: str,
        param_type: type | None = None,
        *,
        help_target: Callable | type | None = None,
        parent=None,
    ) -> None:
        """Show help for a parameter using parameter-help content directly."""
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

            logger.debug("Showing parameter help for %s", param_name)

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

        except Exception as error:
            logger.exception("Failed to show parameter help")
            QMessageBox.warning(parent, "Help Error", f"Failed to show help: {error}")


class HelpableWidget:
    """Mixin class to add help functionality to PyQt6 widgets - mirrors Textual TUI."""

    def show_function_help(self, target: Callable | type) -> None:
        """Show help window for a function or class."""
        HelpWindowManager.show_docstring_help(target, parent=self)

    def show_parameter_help(
        self,
        param_name: str,
        param_description: str,
        param_type: type | None = None,
    ) -> None:
        """Show help window for a parameter."""
        HelpWindowManager.show_parameter_help(
            param_name,
            param_description,
            param_type,
            parent=self,
        )
