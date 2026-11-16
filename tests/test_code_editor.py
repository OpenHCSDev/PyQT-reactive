"""The code editor colours Python by token, carries string state across lines, and
moves to a reported error line."""

from PySide6.QtGui import QTextDocument

from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.widgets.editors.python_highlighter import PythonHighlighter
from pyqt_reactive.widgets.editors.simple_code_editor import CodeEditorDialog


def _colors(document: QTextDocument, line: int) -> dict[int, str]:
    """Foreground colour name at each highlighted column of one line."""
    block = document.findBlockByNumber(line)
    return {
        column: fmt.format.foreground().color().name()
        for fmt in block.layout().formats()
        for column in range(fmt.start, fmt.start + fmt.length)
    }


def test_python_highlighter_colours_tokens_and_multiline_strings(qapp):
    scheme = ColorScheme()
    document = QTextDocument()
    document.setPlainText('def f():\n    """first\n    def not_code\n    """\n    return 1\n')
    PythonHighlighter(document, scheme)

    keyword = scheme.to_hex(scheme.python_keyword_color)
    string = scheme.to_hex(scheme.python_string_color)
    number = scheme.to_hex(scheme.python_number_color)
    assert _colors(document, 0)[0] == keyword  # "def"
    assert _colors(document, 1)[4] == string  # opening of the docstring
    assert set(_colors(document, 2).values()) == {string}  # "def" inside it stays a string
    assert _colors(document, 3)[4] == string  # closing quotes
    assert _colors(document, 4)[4] == keyword  # "return" after the string closed
    assert _colors(document, 4)[11] == number


def test_code_editor_dialog_goes_to_error_line_and_round_trips_content(qapp):
    dialog = CodeEditorDialog(None, "a = 1\nb = 2\nc = 3\n", "Edit", initial_line=2)
    try:
        assert dialog.editor.textCursor().selectedText() == "b = 2"
        dialog.set_content("x = 1\n")
        assert dialog.get_content() == "x = 1\n"
    finally:
        dialog.close()
