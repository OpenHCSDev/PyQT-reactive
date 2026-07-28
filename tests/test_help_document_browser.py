"""Qt tests for the shared rich help-document renderer and popup lifecycle."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QTextCursor

from pyqt_reactive.services.help_document import HelpDocument, HelpDocumentFormat
from pyqt_reactive.widgets.help_document_browser import HelpDocumentBrowser
from pyqt_reactive.windows.help_window_manager import (
    BaseHelpWindow,
    DocstringHelpWindow,
    ParameterHelpWindow,
)


def _show(widget, qapp) -> None:
    widget.show()
    qapp.processEvents()


def _anchor_hrefs(browser: HelpDocumentBrowser) -> set[str]:
    hrefs: set[str] = set()
    block = browser.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                char_format = fragment.charFormat()
                if char_format.isAnchor() and char_format.anchorHref():
                    hrefs.add(char_format.anchorHref())
            iterator += 1
        block = block.next()
    return hrefs


def _anchor_colors(browser: HelpDocumentBrowser) -> set[str]:
    colors: set[str] = set()
    block = browser.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if not fragment.isValid():
                iterator += 1
                continue
            char_format = fragment.charFormat()
            if char_format.isAnchor() and char_format.anchorHref():
                colors.add(char_format.foreground().color().name())
            iterator += 1
        block = block.next()
    return colors


@pytest.mark.parametrize(
    ("markup", "content"),
    [
        (
            HelpDocumentFormat.MARKDOWN,
            (
                "# Main heading\n\n"
                "## Section heading\n\n"
                "See [the reference](https://example.com/reference).\n\n"
                "```python\nresult = process(image)\n```"
            ),
        ),
        (
            HelpDocumentFormat.RESTRUCTURED_TEXT,
            (
                "Main heading\n"
                "============\n\n"
                "Overview text.\n\n"
                "Section heading\n"
                "---------------\n\n"
                "See `the reference <https://example.com/reference>`_.\n\n"
                ".. code-block:: python\n\n"
                "   result = process(image)\n"
            ),
        ),
    ],
)
def test_rich_browser_renders_hierarchy_code_links_and_theme(
    qapp,
    markup: HelpDocumentFormat,
    content: str,
) -> None:
    browser = HelpDocumentBrowser()
    browser.resize(520, 320)
    _show(browser, qapp)

    browser.set_help_document(HelpDocument(content, markup))
    qapp.processEvents()

    heading_levels: list[int] = []
    block = browser.document().begin()
    while block.isValid():
        heading_level = block.blockFormat().headingLevel()
        if heading_level:
            heading_levels.append(heading_level)
        block = block.next()
    assert heading_levels[:2] == [1, 2]
    assert "result = process(image)" in browser.toPlainText()
    assert _anchor_hrefs(browser) == {"https://example.com/reference"}
    assert _anchor_colors(browser) == {"#00aaff"}
    rendered_html = browser.toHtml()
    assert "#00aaff" in rendered_html
    assert "#404040" in rendered_html


def test_plain_text_is_not_reinterpreted_as_markup(qapp) -> None:
    browser = HelpDocumentBrowser()
    _show(browser, qapp)

    browser.set_help_document(
        HelpDocument(
            "# Not a heading\n\n[not a link](https://example.com)",
            HelpDocumentFormat.PLAIN_TEXT,
        )
    )
    qapp.processEvents()

    assert browser.document().begin().blockFormat().headingLevel() == 0
    assert not _anchor_hrefs(browser)
    assert browser.toPlainText().startswith("# Not a heading")


@pytest.mark.parametrize(
    ("markup", "content"),
    [
        (HelpDocumentFormat.PLAIN_TEXT, "Plain help"),
        (HelpDocumentFormat.MARKDOWN, "# Markdown help"),
        (
            HelpDocumentFormat.RESTRUCTURED_TEXT,
            "Restructured help\n=================",
        ),
    ],
)
def test_each_render_branch_preserves_explicit_base_url(
    qapp,
    tmp_path,
    markup: HelpDocumentFormat,
    content: str,
) -> None:
    browser = HelpDocumentBrowser()
    base_path = tmp_path / markup.value

    browser.set_help_document(
        HelpDocument(content, markup, base_url=str(base_path))
    )
    qapp.processEvents()

    assert browser.document().baseUrl() == QUrl.fromLocalFile(str(base_path.resolve()))


def test_reused_browser_resets_base_url_and_scroll_position(qapp, tmp_path) -> None:
    browser = HelpDocumentBrowser()
    browser.resize(320, 160)
    _show(browser, qapp)
    first_base = tmp_path / "first"

    browser.set_help_document(
        HelpDocument(
            "\n\n".join(f"Paragraph {index}" for index in range(80)),
            HelpDocumentFormat.MARKDOWN,
            base_url=str(first_base),
        )
    )
    qapp.processEvents()
    browser.verticalScrollBar().setValue(browser.verticalScrollBar().maximum())
    assert browser.verticalScrollBar().value() > 0
    assert browser.document().baseUrl() == QUrl.fromLocalFile(str(first_base.resolve()))

    browser.set_help_document(HelpDocument("Replacement"))
    qapp.processEvents()

    assert browser.verticalScrollBar().value() == 0
    assert browser.document().baseUrl().isEmpty()


def test_long_prose_and_code_wrap_without_horizontal_overlay(qapp) -> None:
    browser = HelpDocumentBrowser()
    browser.resize(300, 220)
    _show(browser, qapp)
    repeated_prose = " ".join(["readable"] * 120)
    repeated_code = " + ".join(["measurement"] * 80)

    browser.set_help_document(
        HelpDocument(
            f"# Wrapping\n\n{repeated_prose}\n\n```python\n{repeated_code}\n```",
            HelpDocumentFormat.MARKDOWN,
        )
    )
    qapp.processEvents()

    assert browser.verticalScrollBar().maximum() > 0
    assert browser.horizontalScrollBar().maximum() == 0


def test_document_height_comes_from_qt_layout_and_changes_with_width(qapp) -> None:
    browser = HelpDocumentBrowser()
    browser.set_help_document(
        HelpDocument(
            "# Layout\n\n" + " ".join(["wrapped content"] * 120),
            HelpDocumentFormat.MARKDOWN,
        )
    )

    compact_height = browser.document_height_for_width(320)
    wide_height = browser.document_height_for_width(760)

    assert compact_height > wide_height > 0


def test_help_window_uses_real_document_height_at_compact_and_wide_sizes(
    qapp,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        BaseHelpWindow,
        "available_help_bounds",
        lambda self: (900, 720),
    )
    document = HelpDocument(
        "# Responsive help\n\n" + " ".join(["configuration detail"] * 60),
        HelpDocumentFormat.MARKDOWN,
    )
    compact = BaseHelpWindow()
    compact.set_help_document(document, target_width=420)
    _show(compact, qapp)
    wide = BaseHelpWindow()
    wide.set_help_document(document, target_width=820)
    _show(wide, qapp)

    assert compact.width() == 420
    assert wide.width() == 820
    assert compact.content_area.height() > wide.content_area.height()
    assert wide.content_area.horizontalScrollBar().maximum() == 0


def test_docstring_and_parameter_windows_share_only_rich_browser_body(
    qapp,
) -> None:
    def documented(value: int) -> int:
        """Transform a value.

        The operation preserves the declared measurement identity.

        Args:
            value: Input measurement.

        Returns:
            Transformed measurement.

        Examples:
            result = documented(3)
        """
        return value

    docstring_window = DocstringHelpWindow(documented)
    parameter_window = ParameterHelpWindow(
        SimpleNamespace(
            summary="Input measurement.",
            description="Provide the value to transform.",
        )
    )
    _show(docstring_window, qapp)
    _show(parameter_window, qapp)

    assert isinstance(docstring_window.content_area, HelpDocumentBrowser)
    assert isinstance(parameter_window.content_area, HelpDocumentBrowser)
    assert "Transform a value." in docstring_window.content_area.toPlainText()
    assert "Input measurement." in parameter_window.content_area.toPlainText()


def test_setting_document_moves_cursor_to_start(qapp) -> None:
    browser = HelpDocumentBrowser()
    browser.set_help_document(
        HelpDocument("\n\n".join(f"Paragraph {index}" for index in range(20)))
    )
    cursor = browser.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    browser.setTextCursor(cursor)

    browser.set_help_document(HelpDocument("Replacement"))

    assert browser.textCursor().position() == 0
