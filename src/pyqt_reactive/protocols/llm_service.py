"""LLM service protocol for pluggable code generation backends."""

from typing import List, Optional, Protocol, Tuple, TypeVar


DeclarationT = TypeVar("DeclarationT")


class LLMServiceProtocol(Protocol):
    """Protocol for LLM services used by LLMChatPanel."""

    api_endpoint: str
    model: Optional[str]

    def test_connection(self) -> Tuple[bool, str]:
        """Return (is_connected, status_message)."""
        ...

    def _get_available_models(self) -> List[str]:
        """Return list of available model names."""
        ...

    def get_system_prompt(self, declaration_type: type[DeclarationT]) -> str:
        """Return the prompt for the nominal declaration being authored."""
        ...

    def generate_code(
        self,
        request: str,
        declaration_type: type[DeclarationT],
    ) -> str:
        """Generate code for a nominal declaration type."""
        ...


_llm_service: Optional[LLMServiceProtocol] = None


def register_llm_service(service: LLMServiceProtocol) -> None:
    """Register a global LLM service implementation."""
    global _llm_service
    _llm_service = service


def get_llm_service() -> Optional[LLMServiceProtocol]:
    """Get the registered LLM service implementation."""
    return _llm_service
