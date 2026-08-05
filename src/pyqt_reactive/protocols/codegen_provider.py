"""Code generation provider protocol for app-specific code emitters."""

from typing import Protocol, TypeVar


DeclarationT = TypeVar("DeclarationT")


class CodegenProvider(Protocol):
    """Protocol for code generators used by the simple code editor."""

    def render_assignment(
        self,
        value: object,
        *,
        assignment_name: str,
        header: str,
        clean_mode: bool,
    ) -> str: ...

    def normalize_source(
        self,
        source: str,
        *,
        declaration_type: type[DeclarationT],
        clean_mode: bool,
    ) -> str: ...


_codegen_provider: CodegenProvider | None = None


def register_codegen_provider(provider: CodegenProvider) -> None:
    """Register a global code generation provider."""
    global _codegen_provider
    _codegen_provider = provider


def get_codegen_provider() -> CodegenProvider | None:
    """Get the registered code generation provider."""
    return _codegen_provider
