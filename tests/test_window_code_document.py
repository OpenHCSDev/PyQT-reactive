"""Document-local revision ownership for managed window code documents."""

from __future__ import annotations

import pytest

from pyqt_reactive.services.window_code_document import (
    WindowCodeDocument,
    WindowCodeDocumentDriver,
)


class MutableCodeDocumentDriver(WindowCodeDocumentDriver):
    def __init__(self, source: str) -> None:
        self.source = source

    def read_document(self, clean: bool = True) -> WindowCodeDocument:
        del clean
        return WindowCodeDocument(title="Mutable document", source=self.source)

    def validate_source(self, source: str) -> None:
        if source == "invalid":
            raise ValueError("invalid source")

    def apply_source(self, source: str) -> None:
        self.validate_source(source)
        self.source = source


def test_default_revision_tracks_document_content_not_rejected_validation() -> None:
    driver = MutableCodeDocumentDriver("original")
    original_revision = driver.current_revision_token()

    with pytest.raises(ValueError, match="invalid source"):
        driver.validate_source("invalid")

    assert driver.current_revision_token() == original_revision
    driver.apply_source("replacement")
    assert driver.current_revision_token() != original_revision
