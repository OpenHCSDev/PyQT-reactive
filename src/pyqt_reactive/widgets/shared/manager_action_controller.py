"""Qt code-editor surface implementing formbridge's InteractiveCodeEditorSurface."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from formbridge.managers.action_controller import InteractiveCodeEditorSurface

from pyqt_reactive.widgets.editors.simple_code_editor import SimpleCodeEditorService


class QtCodeEditorSurface(InteractiveCodeEditorSurface):
    """Opens SimpleCodeEditorService parented to a Qt manager widget."""

    def __init__(self, widget: Any) -> None:
        self._widget = widget

    def edit_code(
        self,
        *,
        initial_content: str,
        title: str,
        callback: Callable[[str], None],
        use_external: bool,
        declaration_type: type[Any] | None,
        code_data: dict[str, Any],
    ) -> None:
        editor_service = SimpleCodeEditorService(self._widget)
        editor_service.edit_code(
            initial_content=initial_content,
            title=title,
            callback=callback,
            use_external=use_external,
            declaration_type=declaration_type,
            code_data=code_data,
        )
