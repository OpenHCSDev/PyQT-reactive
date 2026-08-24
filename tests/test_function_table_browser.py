"""Nominal function-table presentation contracts."""

import pytest

from pyqt_reactive.widgets.shared.function_table_browser import (
    FunctionTableBrowser,
    FunctionTableRow,
)


def test_function_table_rejects_structural_domain_rows_before_state_changes(qapp) -> None:
    row = FunctionTableRow(
        name="normalize",
        module="example.processing",
        library="example",
        backend_tags=("cpu",),
        summary="Normalize an image.",
    )
    browser = FunctionTableBrowser()
    browser.set_items({"normalize": row})

    class StructuralRow:
        name = row.name
        module = row.module
        library = row.library
        backend_tags = row.backend_tags
        summary = row.summary

    with pytest.raises(TypeError, match="FunctionTableRow"):
        browser.set_items({"structural": StructuralRow()})

    assert browser.all_items == {"normalize": row}
