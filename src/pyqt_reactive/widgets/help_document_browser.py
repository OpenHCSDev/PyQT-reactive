"""Rich, scrollable renderer for generic help documents."""

from __future__ import annotations

from math import ceil
from pathlib import Path, PureWindowsPath

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QBrush, QTextCharFormat, QTextCursor, QTextDocument, QTextOption
from PyQt6.QtWidgets import QTextBrowser

from pyqt_reactive.services.help_document import HelpDocument, HelpDocumentFormat
from pyqt_reactive.theming import ColorScheme

HELP_DOCUMENT_PADDING = 8


class HelpDocumentBrowser(QTextBrowser):
    """Render plain text, Markdown, and reStructuredText through one widget."""

    def __init__(
        self,
        *,
        color_scheme: ColorScheme | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.color_scheme = color_scheme or ColorScheme()
        self.current_document: HelpDocument | None = None
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setOpenLinks(True)
        self.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(self._widget_style())

    def set_help_document(self, document: HelpDocument) -> None:
        """Render one typed document and reset the viewport to its beginning."""
        self.current_document = document
        self.clear()
        self.document().setDefaultStyleSheet(self._document_style())
        self.document().setBaseUrl(self._base_url(document))

        if document.markup is HelpDocumentFormat.MARKDOWN:
            markdown_document = QTextDocument()
            markdown_document.setMarkdown(document.content)
            self.setHtml(markdown_document.toHtml())
        elif document.markup is HelpDocumentFormat.RESTRUCTURED_TEXT:
            self.setHtml(document.rendered_html())
        else:
            self.setPlainText(document.content)

        self._apply_link_style()
        self.moveCursor(QTextCursor.MoveOperation.Start)

    def document_height_for_width(self, widget_width: int) -> int:
        """Return the document's Qt-laid-out outer height at one widget width."""
        available_width = max(
            1,
            widget_width - (self.frameWidth() * 2) - (HELP_DOCUMENT_PADDING * 2),
        )
        layout_document = self.document().clone()
        layout_document.setTextWidth(available_width)
        document_height = layout_document.documentLayout().documentSize().height()
        return ceil(document_height + (self.frameWidth() * 2) + (HELP_DOCUMENT_PADDING * 2))

    @staticmethod
    def _base_url(document: HelpDocument) -> QUrl:
        if not document.base_url:
            return QUrl()
        if PureWindowsPath(document.base_url).drive:
            return QUrl.fromLocalFile(document.base_url.replace("\\", "/"))
        base_url = QUrl(document.base_url)
        if base_url.scheme() == "":
            return QUrl.fromLocalFile(str(Path(document.base_url).resolve()))
        return base_url

    def _apply_link_style(self) -> None:
        """Apply the active theme to anchors imported by Qt's markup parsers."""
        anchor_ranges: list[tuple[int, int]] = []
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if not fragment.isValid():
                    iterator += 1
                    continue
                char_format = fragment.charFormat()
                if char_format.isAnchor() and char_format.anchorHref():
                    anchor_ranges.append((fragment.position(), fragment.length()))
                iterator += 1
            block = block.next()

        anchor_format = QTextCharFormat()
        anchor_format.setForeground(
            QBrush(self.color_scheme.to_qcolor(self.color_scheme.text_accent))
        )
        anchor_format.setFontUnderline(True)
        cursor = QTextCursor(self.document())
        for position, length in anchor_ranges:
            cursor.setPosition(position)
            cursor.setPosition(
                position + length,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.mergeCharFormat(anchor_format)

    def _widget_style(self) -> str:
        scheme = self.color_scheme
        return (
            "QTextBrowser {"
            f"background-color: {scheme.to_hex(scheme.panel_bg)};"
            f"color: {scheme.to_hex(scheme.text_primary)};"
            f"border: 1px solid {scheme.to_hex(scheme.border_color)};"
            f"padding: {HELP_DOCUMENT_PADDING}px;"
            "}"
        )

    def _document_style(self) -> str:
        scheme = self.color_scheme
        primary = scheme.to_hex(scheme.text_primary)
        secondary = scheme.to_hex(scheme.text_secondary)
        accent = scheme.to_hex(scheme.text_accent)
        code_background = scheme.to_hex(scheme.input_bg)
        border = scheme.to_hex(scheme.border_color)
        return f"""
            body {{ color: {primary}; line-height: 1.35; }}
            h1 {{ color: {accent}; font-size: 20px; margin: 12px 0 8px 0; }}
            h2 {{ color: {accent}; font-size: 17px; margin: 14px 0 6px 0; }}
            h3 {{ color: {secondary}; font-size: 14px; margin: 12px 0 4px 0; }}
            h4, h5, h6 {{ color: {secondary}; margin: 10px 0 4px 0; }}
            p {{ margin: 4px 0 8px 0; }}
            ul, ol {{ margin: 4px 0 8px 18px; }}
            li {{ margin: 2px 0; }}
            a {{ color: {accent}; text-decoration: underline; }}
            code {{
                color: {primary};
                background-color: {code_background};
                font-family: monospace;
            }}
            pre {{
                color: {primary};
                background-color: {code_background};
                border: 1px solid {border};
                font-family: monospace;
                white-space: pre-wrap;
                margin: 8px 0;
                padding: 8px;
            }}
            blockquote {{
                color: {secondary};
                border-left: 3px solid {accent};
                margin: 8px 0;
                padding-left: 10px;
            }}
            table {{ border-collapse: collapse; margin: 8px 0; }}
            th, td {{ border: 1px solid {border}; padding: 4px 6px; }}
        """
