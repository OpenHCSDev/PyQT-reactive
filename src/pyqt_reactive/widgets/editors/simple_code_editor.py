"""
Code editor for Python source: a floating dialog over a line-numbered, highlighted
QPlainTextEdit, or an external program from $EDITOR.
"""

import hashlib
import logging
import os
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QAction, QFont, QKeyEvent, QKeySequence, QPainter, QPaintEvent, QResizeEvent, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from formbridge.core.path_cache import CodeEditor, cache_path, get_initial_path
from formbridge.protocols.codegen_provider import get_codegen_provider
from formbridge.services.window_code_document import (
    PYTHON_MIME_TYPE,
    WindowCodeDocument,
    WindowCodeDocumentDriver,
)
from pyqt_reactive.services.window_manager import WindowManager
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.editors.python_highlighter import PythonHighlighter

logger = logging.getLogger(__name__)
DeclarationT = TypeVar("DeclarationT")
INDENT = "    "


class SimpleCodeEditorWindowCodeDocumentDriver(
    WindowCodeDocumentDriver[DeclarationT],
    Generic[DeclarationT],
):
    """WindowManager code-document driver for floating simple code editors."""

    def __init__(
        self,
        *,
        dialog: QDialog,
        title: str,
        callback: Callable[[str], None] | None,
        declaration_type: type[DeclarationT] | None,
    ) -> None:
        self._dialog = dialog
        self._title = title
        self._callback = callback
        self._declaration_type = declaration_type

    def read_document(self, clean: bool = True) -> WindowCodeDocument[DeclarationT]:
        return WindowCodeDocument(
            title=self._title,
            source=self._content(),
            mime_type=PYTHON_MIME_TYPE,
            declaration_type=self._declaration_type,
        )

    def current_revision_token(self) -> str:
        return hashlib.sha256(self._content().encode("utf-8")).hexdigest()

    def records_object_state_snapshot_on_apply(self) -> bool:
        return False

    def validate_source(self, source: str) -> None:
        compile(source, f"<{self._title}>", "exec")

    def apply_source(self, source: str) -> None:
        self.validate_source(source)
        if self._callback is not None:
            self._callback(source)
        self._set_content(source)

    def _content(self) -> str:
        return self._dialog.get_content()

    def _set_content(self, source: str) -> None:
        self._dialog.set_content(source)


class SimpleCodeEditorService(Generic[DeclarationT]):
    """
    Simple, modular code editor service.

    Opens a CodeEditorDialog, or the external program named by $EDITOR.
    No threading - keeps it simple and reliable.
    """
    
    def __init__(self, parent_widget):
        """
        Initialize the code editor service.

        Args:
            parent_widget: Parent widget for dialogs
        """
        self.parent = parent_widget

    def edit_code(self, initial_content: str, title: str = "Edit Code",
                  callback: Callable[[str], None] | None = None,
                  use_external: bool = False,
                  declaration_type: type[DeclarationT] | None = None,
                  code_data: dict = None) -> None:
        """
        Edit code using either Qt native editor or external program.

        Args:
            initial_content: Initial code content
            title: Editor window title
            callback: Callback function called with edited content
            use_external: If True, use external editor; if False, use Qt native
            declaration_type: Nominal type of the declaration being edited.
            code_data: Data needed to regenerate code (for clean mode toggle)
        """
        if use_external:
            self._edit_with_external_program(initial_content, callback)
        else:
            self._edit_with_qt_native(
                initial_content,
                title,
                callback,
                declaration_type,
                code_data,
            )
    
    def _edit_with_qt_native(self, initial_content: str, title: str,
                           callback: Callable[[str], None] | None,
                           declaration_type: type[DeclarationT] | None = None,
                           code_data: dict = None,
                           error_line: int = None) -> None:
        """Edit code in a floating CodeEditorDialog."""
        try:
            dialog = CodeEditorDialog(self.parent, initial_content, title,
                                      callback=callback,
                                      declaration_type=declaration_type,
                                      code_data=code_data,
                                      initial_line=error_line)

            # Show dialog as non-blocking floating window (like other OpenHCS windows)
            # Use .show() instead of .exec() to allow interaction with other windows
            self._register_code_document_window(
                dialog,
                title=title,
                callback=callback,
                declaration_type=declaration_type,
            )
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

        except Exception as e:
            logger.error(f"Qt native editor failed: {e}")
            self._show_error(f"Editor failed: {str(e)}")

    def _register_code_document_window(
        self,
        dialog: QDialog,
        *,
        title: str,
        callback: Callable[[str], None] | None,
        declaration_type: type[DeclarationT] | None = None,
    ) -> None:
        """Expose the floating editor through WindowManager code-document APIs."""
        scope_type = (
            "code"
            if declaration_type is None
            else f"{declaration_type.__module__}.{declaration_type.__qualname__}"
        )
        scope_id = f"code_editor:{scope_type}:{id(dialog)}"
        WindowManager.register(
            scope_id,
            dialog,
            code_document_driver=SimpleCodeEditorWindowCodeDocumentDriver(
                dialog=dialog,
                title=title,
                callback=callback,
                declaration_type=declaration_type,
            ),
        )

        def unregister() -> None:
            WindowManager.unregister(scope_id, dialog)

        dialog.finished.connect(lambda _result: unregister())
        dialog.destroyed.connect(lambda _obj=None: unregister())
    
    def _edit_with_external_program(self, initial_content: str,
                                  callback: Callable[[str], None] | None) -> None:
        """Edit code using external program (vim, nano, vscode, etc.)."""
        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(initial_content)
                temp_path = Path(f.name)
            
            # Get editor from environment or use default
            editor = os.environ.get('EDITOR', 'nano')
            
            # Launch editor and wait for completion
            result = subprocess.run([editor, str(temp_path)], 
                                  capture_output=False, 
                                  text=True)
            
            if result.returncode == 0:
                # Read edited content
                with open(temp_path, 'r') as f:
                    edited_content = f.read()
                
                if callback:
                    callback(edited_content)
            else:
                self._show_error(f"Editor exited with code {result.returncode}")
                
        except FileNotFoundError:
            self._show_error(f"Editor '{editor}' not found. Set EDITOR environment variable or install nano/vim.")
        except Exception as e:
            logger.error(f"External editor failed: {e}")
            self._show_error(f"External editor failed: {str(e)}")
        finally:
            # Clean up temporary file
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except:
                pass
    
    def _show_error(self, message: str) -> None:
        """Show error message to user."""
        QMessageBox.critical(self.parent, "Editor Error", message)

class LineNumberGutter(QWidget):
    """The strip left of a CodeTextEdit that paints its visible line numbers."""

    def __init__(self, editor: "CodeTextEdit") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt virtual method name
        self._editor.paint_gutter(self, event)


class CodeTextEdit(QPlainTextEdit):
    """Python source editing: monospace text, Python highlighting, line numbers,
    a highlighted current line, four-space indents and auto-indent on Enter."""

    def __init__(self, color_scheme: ColorScheme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color_scheme = color_scheme
        self._gutter = LineNumberGutter(self)
        self.highlighter = PythonHighlighter(self.document(), color_scheme)

        font = QFont("Consolas", 10)
        if not font.exactMatch():
            font = QFont("Courier New", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * len(INDENT))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_gutter_width()
        self._highlight_current_line()

    # Line numbers
    def gutter_width(self) -> int:
        if self._gutter.isHidden():
            return 0
        digits = max(4, len(str(max(1, self.blockCount()))))
        return 6 + self.fontMetrics().horizontalAdvance("9") * digits

    def set_line_numbers_visible(self, visible: bool) -> None:
        self._gutter.setVisible(visible)
        self._update_gutter_width()

    def _update_gutter_width(self, _block_count: int = 0) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt virtual method name
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._gutter.setGeometry(QRect(contents.left(), contents.top(), self.gutter_width(), contents.height()))

    def paint_gutter(self, gutter: QWidget, event: QPaintEvent) -> None:
        cs = self._color_scheme
        painter = QPainter(gutter)
        painter.fillRect(event.rect(), cs.to_qcolor(cs.frame_bg))
        painter.setPen(cs.to_qcolor(cs.text_secondary))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            bottom = top + round(self.blockBoundingRect(block).height())
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    0, top, gutter.width() - 3, height,
                    Qt.AlignmentFlag.AlignRight, str(block.blockNumber() + 1),
                )
            block = block.next()
            top = bottom
        painter.end()

    # Current line
    def _highlight_current_line(self) -> None:
        cs = self._color_scheme
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(cs.to_qcolor(cs.frame_bg))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    # Indentation
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt virtual method name
        if event.key() == Qt.Key.Key_Tab and not self.textCursor().hasSelection():
            self.insertPlainText(INDENT)
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            line = self.textCursor().block().text()
            indent = line[: len(line) - len(line.lstrip())]
            if line.rstrip().endswith(":"):
                indent += INDENT
            super().keyPressEvent(event)
            self.insertPlainText(indent)
            return
        super().keyPressEvent(event)

    def goto_line(self, line_number: int) -> None:
        """Select line `line_number` (1-based) and scroll it into view."""
        block = self.document().findBlockByNumber(line_number - 1)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.centerCursor()


class CodeEditorDialog(QDialog, Generic[DeclarationT]):
    """
    Floating Python code editor dialog.

    Line numbers and Python highlighting from the ColorScheme; supports the clean
    mode toggle for orchestrator/pipeline/function code.
    """

    def __init__(self, parent, initial_content: str, title: str,
                 callback: Callable[[str], None] | None = None,
                 declaration_type: type[DeclarationT] | None = None,
                 code_data: dict = None, initial_line: int = None):
        """
        Initialize code editor dialog.

        Args:
            parent: Parent widget
            initial_content: Initial code content
            title: Window title
            callback: Callback function called with edited content on successful save
            declaration_type: Nominal type of the declaration being edited.
            code_data: Data needed to regenerate code (for clean mode toggle)
            initial_line: Line number to position cursor at (1-based, None for start)
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)  # Non-modal - allow other windows to be interactable
        self.resize(900, 700)

        self.callback = callback
        self.declaration_type = declaration_type
        self.code_data = code_data or {}
        self.clean_mode = self.code_data.get('clean_mode', True)  # Default to clean mode
        self.color_scheme = ColorScheme()

        main_layout = QVBoxLayout(self)
        self._setup_menu_bar()
        self.menu_bar.setMaximumHeight(25)
        main_layout.addWidget(self.menu_bar, 0)

        self.editor = CodeTextEdit(self.color_scheme, self)
        self.editor.setPlainText(initial_content)
        main_layout.addWidget(self.editor)

        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        # Shift+Click saves without closing
        self.save_btn.clicked.connect(self._on_save_clicked)
        button_layout.addWidget(self.save_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        self._apply_theme()

        if initial_line is not None:
            self._goto_line(initial_line)
        self.editor.setFocus()

    def _setup_menu_bar(self):
        """Setup menu bar with File, Edit, View menus."""
        self.menu_bar = QMenuBar(self)

        file_menu = self.menu_bar.addMenu("&File")
        self._add_action(file_menu, "&New", QKeySequence.StandardKey.New, self._new_file)
        self._add_action(file_menu, "&Open...", QKeySequence.StandardKey.Open, self._open_file)
        file_menu.addSeparator()
        self._add_action(file_menu, "&Save", QKeySequence.StandardKey.Save, self.accept)
        self._add_action(file_menu, "Save &As...", QKeySequence.StandardKey.SaveAs, self._save_as)
        file_menu.addSeparator()
        self._add_action(file_menu, "&Close", QKeySequence.StandardKey.Close, self.reject)

        edit_menu = self.menu_bar.addMenu("&Edit")
        self._add_action(edit_menu, "&Undo", QKeySequence.StandardKey.Undo, lambda: self.editor.undo())
        self._add_action(edit_menu, "&Redo", QKeySequence.StandardKey.Redo, lambda: self.editor.redo())
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Cu&t", QKeySequence.StandardKey.Cut, lambda: self.editor.cut())
        self._add_action(edit_menu, "&Copy", QKeySequence.StandardKey.Copy, lambda: self.editor.copy())
        self._add_action(edit_menu, "&Paste", QKeySequence.StandardKey.Paste, lambda: self.editor.paste())
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Select &All", QKeySequence.StandardKey.SelectAll, lambda: self.editor.selectAll())

        view_menu = self.menu_bar.addMenu("&View")
        toggle_line_numbers = QAction("Toggle &Line Numbers", self)
        toggle_line_numbers.setCheckable(True)
        toggle_line_numbers.setChecked(True)
        toggle_line_numbers.triggered.connect(lambda checked: self.editor.set_line_numbers_visible(checked))
        view_menu.addAction(toggle_line_numbers)
        view_menu.addSeparator()
        toggle_clean_mode = QAction("Toggle &Clean Mode", self)
        toggle_clean_mode.setCheckable(True)
        toggle_clean_mode.setChecked(self.clean_mode)
        toggle_clean_mode.triggered.connect(self._toggle_clean_mode)
        view_menu.addAction(toggle_clean_mode)

    def _add_action(self, menu, text: str, shortcut: QKeySequence.StandardKey, slot) -> None:
        action = QAction(text, self)
        action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)

    def _apply_theme(self):
        """The dialog surface and the editor's text colours from the ColorScheme; buttons
        use the application's shared button style."""
        cs = self.color_scheme
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {cs.to_hex(cs.window_bg)};
                color: {cs.to_hex(cs.text_primary)};
            }}
            CodeTextEdit {{
                background-color: {cs.to_hex(cs.panel_bg)};
                color: {cs.to_hex(cs.text_primary)};
                selection-background-color: {cs.to_hex(cs.selection_bg)};
                selection-color: {cs.to_hex(cs.selection_text)};
            }}
        """ + cs.styles.generate_button_style())

    def _new_file(self):
        """Clear editor content."""
        self.editor.clear()

    def _open_file(self):
        """Open file dialog and load content."""
        # Get cached initial directory
        initial_dir = str(get_initial_path(CodeEditor, fallback=Path.home()))

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Python File", initial_dir, "Python Files (*.py);;All Files (*)"
        )
        if file_path:
            try:
                selected_path = Path(file_path)
                # Cache the parent directory for future dialogs
                cache_path(CodeEditor, selected_path.parent)

                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.editor.setPlainText(content)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open file: {str(e)}")

    def _save_as(self):
        """Save content to file."""
        # Get cached initial directory
        initial_dir = str(get_initial_path(CodeEditor, fallback=Path.home()))

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Python File", initial_dir, "Python Files (*.py);;All Files (*)"
        )
        if file_path:
            try:
                selected_path = Path(file_path)

                # Ensure file always ends with .py extension
                if not selected_path.suffix.lower() == '.py':
                    selected_path = selected_path.with_suffix('.py')
                    file_path = str(selected_path)

                # Cache the parent directory for future dialogs
                cache_path(CodeEditor, selected_path.parent)

                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.editor.toPlainText())
                QMessageBox.information(self, "Success", f"File saved to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save file: {str(e)}")

    def _toggle_clean_mode(self, checked):
        """Toggle between clean mode (minimal) and explicit mode (full)."""
        try:
            current_code = self.editor.toPlainText()
            provider = get_codegen_provider()
            if provider is None:
                QMessageBox.warning(self, "Clean Mode Toggle",
                                  "No codegen provider registered. Call register_codegen_provider(...) in the host app.")
                return

            if self.declaration_type is None:
                QMessageBox.warning(self, "Clean Mode Toggle",
                                  "This editor has no nominal declaration type.")
                return

            new_code = provider.normalize_source(
                current_code,
                declaration_type=self.declaration_type,
                clean_mode=checked,
            )
            self.clean_mode = checked
            self.code_data['clean_mode'] = self.clean_mode
            self.editor.setPlainText(new_code)

        except Exception as e:
            logger.error(f"Failed to toggle clean mode: {e}\n{traceback.format_exc()}")

            QMessageBox.critical(self, "Clean Mode Toggle Error",
                               f"Failed to toggle clean mode: {str(e)}")

    def get_content(self) -> str:
        """Get the edited content."""
        return self.editor.toPlainText()

    def set_content(self, content: str) -> None:
        """Replace the edited content."""
        self.editor.setPlainText(content)

    def _on_save_clicked(self) -> None:
        """Handle save button click with Shift+Click detection."""
        modifiers = QApplication.keyboardModifiers()
        is_shift = modifiers & Qt.KeyboardModifier.ShiftModifier
        self._handle_save(close_window=not is_shift)

    def _handle_save(self, *, close_window=True) -> None:
        """
        Handle save button click - validate code before closing.
        Only closes dialog if callback succeeds and close_window=True, otherwise shows error and keeps dialog open.

        Args:
            close_window: If True, close dialog after successful save. If False (Shift+Click), keep open.
        """
        logger.info(f"Save button clicked (close_window={close_window})")

        if self.callback is None:
            # No callback, just close if requested
            if close_window:
                logger.info("No callback, closing dialog")
                self.accept()
            return

        edited_content = self.get_content()

        try:
            # Try to execute the callback
            logger.info("Executing callback...")
            self.callback(edited_content)
            # Success - close the dialog only if close_window=True
            if close_window:
                logger.info("Callback succeeded, closing dialog")
                self.accept()
            else:
                logger.info("Callback succeeded, keeping dialog open (Shift+Click)")

        except Exception as e:
            # Error - extract line number and show error
            logger.error(f"Callback failed with error: {e}")
            error_line = self._extract_error_line(e)
            logger.info(f"Extracted error line: {error_line}")

            # Show error message
            error_msg = str(e)
            if error_line:
                error_msg = f"Line {error_line}: {error_msg}"

            QMessageBox.critical(self, "Error Parsing Code", error_msg)

            # Move cursor to error line
            if error_line:
                logger.info(f"Moving cursor to line {error_line}")
                self._goto_line(error_line)

            logger.info("Keeping dialog open for user to fix error")
            # Keep dialog open - user can fix the error or click Cancel
            # Do NOT call self.accept() or self.reject() here

    def _extract_error_line(self, exception: Exception) -> int | None:
        """Extract line number from exception if available."""
        # For SyntaxError, use lineno attribute
        if isinstance(exception, SyntaxError) and hasattr(exception, 'lineno'):
            return exception.lineno

        # For other exceptions, try to extract from traceback
        tb = sys.exc_info()[2]
        if tb:
            # Find the frame that executed the user's code (marked as '<string>')
            for frame_summary in traceback.extract_tb(tb):
                if '<string>' in frame_summary.filename:
                    return frame_summary.lineno

        return None

    def _goto_line(self, line_number: int) -> None:
        """Select line `line_number` (1-based) and scroll it into view."""
        if line_number is None or line_number < 1:
            return
        self.editor.goto_line(line_number)
