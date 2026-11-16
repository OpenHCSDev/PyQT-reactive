"""Python syntax highlighting for a QTextDocument, lexed by Pygments one line at a time."""

from pygments.lexers import PythonLexer
from pygments.token import Comment, Keyword, Name, Number, Operator, Punctuation, String, _TokenType
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QTextDocument

from pyqt_reactive.theming import ColorScheme

TRIPLE_QUOTES = ('"""', "'''")


class PythonHighlighter(QSyntaxHighlighter):
    """Colours Python source. Each block (line) is lexed alone; a line that ends inside
    a triple-quoted string records which delimiter is open as its block state, and the
    next line is lexed with that delimiter in front, so a docstring stays a string."""

    def __init__(self, document: QTextDocument, color_scheme: ColorScheme) -> None:
        self._lexer = PythonLexer(stripnl=False, ensurenl=False)
        self._formats: dict[_TokenType, QTextCharFormat] = {}
        super().__init__(document)
        self.set_color_scheme(color_scheme)

    def set_color_scheme(self, cs: ColorScheme) -> None:
        """Which colour each Pygments token family is drawn in. A token takes the colour
        of its nearest listed ancestor (Name.Builtin.Pseudo -> Name.Builtin)."""
        colors = {
            Keyword: cs.python_keyword_color,
            Name: cs.python_name_color,
            Name.Builtin: cs.python_builtin_color,
            Name.Function: cs.python_function_color,
            Name.Decorator: cs.python_function_color,
            Name.Class: cs.python_class_color,
            String: cs.python_string_color,
            Number: cs.python_number_color,
            Operator: cs.python_operator_color,
            Punctuation: cs.python_operator_color,
            Comment: cs.python_comment_color,
        }
        self._formats = {}
        for token, color in colors.items():
            text_format = QTextCharFormat()
            text_format.setForeground(cs.to_qcolor(color))
            self._formats[token] = text_format
        self.rehighlight()

    def _format_for(self, token: _TokenType) -> QTextCharFormat | None:
        while token not in self._formats and token.parent is not None:
            token = token.parent
        return self._formats.get(token)

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt virtual method name
        state = self.previousBlockState()
        prefix = TRIPLE_QUOTES[state] if state >= 0 else ""
        open_quote = ""  # the prefix's own opening token sets it
        for index, token, value in self._lexer.get_tokens_unprocessed(prefix + text):
            if token in String and value in TRIPLE_QUOTES:
                open_quote = "" if open_quote == value else open_quote or value
            text_format = self._format_for(token)
            start = max(index - len(prefix), 0)
            end = index + len(value) - len(prefix)
            if text_format is not None and end > start:
                self.setFormat(start, end - start, text_format)
        self.setCurrentBlockState(TRIPLE_QUOTES.index(open_quote) if open_quote else -1)
