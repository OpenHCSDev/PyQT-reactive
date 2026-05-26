"""Config resolution helpers for manager widgets."""

from __future__ import annotations

from typing import Any


class ManagerGuiConfigResolution:
    """Resolves an optional manager GUI config without discarding valid falsy configs."""

    @staticmethod
    def resolve(candidate: Any) -> Any:
        if candidate is not None:
            return candidate

        from pyqt_reactive.protocols import get_form_config

        return get_form_config()
