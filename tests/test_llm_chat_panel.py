"""Tests for the generic LLM chat panel service boundary."""

from unittest.mock import Mock

from pyqt_reactive.widgets.llm_chat_panel import LLMChatPanel


class _Service:
    def __init__(self) -> None:
        self.api_endpoint = "http://old.example/api/generate"
        self.model: str | None = "old-model"
        self.connection_updates: list[tuple[str, str | None]] = []

    def test_connection(self) -> tuple[bool, str]:
        return True, "connected"

    def _get_available_models(self) -> list[str]:
        return ["old-model", "new-model"]

    def configure_connection(
        self,
        *,
        api_endpoint: str,
        model: str | None,
    ) -> None:
        self.api_endpoint = api_endpoint
        self.model = model
        self.connection_updates.append((api_endpoint, model))

    def get_system_prompt(self, declaration_type: type[object]) -> str:
        del declaration_type
        return "prompt"

    def generate_code(self, request: str, declaration_type: type[object]) -> str:
        del request, declaration_type
        return "result"


def test_connection_settings_preserve_the_registered_service(qapp, monkeypatch) -> None:
    service = _Service()
    panel = LLMChatPanel(declaration_type=dict, llm_service=service)
    refresh = Mock()
    panel._status_indicator.refresh = refresh
    registered: list[object] = []
    monkeypatch.setattr(
        "pyqt_reactive.widgets.llm_chat_panel.register_llm_service",
        registered.append,
    )

    panel._apply_connection_settings(
        "http://new.example/api/generate",
        "new-model",
    )

    assert panel.llm_service is service
    assert service.connection_updates == [
        ("http://new.example/api/generate", "new-model")
    ]
    assert registered == [service]
    refresh.assert_called_once_with(force=True)
    panel.close()
