"""Action and code-editor workflows for manager widgets."""

from __future__ import annotations

import inspect
import logging
import os
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodeEditorPayload:
    """Declarative payload for the manager code editor template."""

    content: str = ""
    code_type: str = "python"
    title: str = "Code Editor"
    data: dict[str, Any] = field(default_factory=dict)
    missing_error_message: str = "No valid assignments found in edited code"


@dataclass(frozen=True)
class ManagerActionOperations:
    """Nominal operation port consumed by ManagerActionController."""

    widget: Any
    action_registry: Mapping[str, str]
    dynamic_actions: Mapping[str, str]
    resolve_method: Callable[[str], Callable[..., Any]]
    run_async: Callable[[Callable[..., Any]], None]
    selected_items: Callable[[], list[Any]]
    item_name_singular: str
    item_name_plural: str
    show_error: Callable[[str], None]
    validate_delete: Callable[[list[Any]], bool]
    perform_delete: Callable[[list[Any]], None]
    update_item_list: Callable[[], None]
    emit_items_changed: Callable[[], None]
    emit_status: Callable[[str], None]
    show_item_editor: Callable[[Any], None]
    validate_code_action: Callable[[], bool]
    code_payload: Any
    pre_code_execution: Callable[[], None]
    patch_lazy_constructors: Callable[[], AbstractContextManager[Any]]
    migrate_code_namespace: Callable[[str, Exception, dict], Optional[dict]]
    apply_code_namespace: Callable[[dict], bool]
    post_code_execution: Callable[[], None]


class ManagerActionController:
    """Owns manager action dispatch, CRUD templates, and edited-code execution."""

    def dispatch(self, operations: ManagerActionOperations, action: str) -> None:
        action_func = self._resolve_action(operations, action)
        if action_func is None:
            logger.warning("Unknown action: %s", action)
            return

        if inspect.iscoroutinefunction(action_func):
            operations.run_async(action_func)
        else:
            action_func()

    def delete_selected(self, operations: ManagerActionOperations) -> None:
        items = operations.selected_items()
        if not items:
            operations.show_error(f"No {operations.item_name_plural} selected")
            return

        if operations.validate_delete(items):
            operations.perform_delete(items)
            operations.update_item_list()
            operations.emit_items_changed()
            operations.emit_status(f"Deleted {len(items)} {operations.item_name_plural}")

    def edit_selected(self, operations: ManagerActionOperations) -> None:
        items = operations.selected_items()
        if not items:
            operations.show_error(f"No {operations.item_name_singular} selected")
            return

        operations.show_item_editor(items[0])

    def open_code_editor(self, operations: ManagerActionOperations) -> None:
        if not operations.validate_code_action():
            return

        payload = operations.code_payload
        if not payload.content:
            operations.show_error("No code to display")
            return

        self.show_code_editor(
            operations=operations,
            code=payload.content,
            title=payload.title,
            callback=lambda edited_code: self.apply_edited_code(operations, edited_code),
            code_type=payload.code_type,
            code_data=dict(payload.data),
        )

    def apply_edited_code(self, operations: ManagerActionOperations, code: str) -> None:
        payload = operations.code_payload
        code_type = payload.code_type
        logger.debug("%s code edited, processing changes...", code_type)
        try:
            if not isinstance(code, str):
                logger.error("Expected string, got %s: %s", type(code), code)
                raise ValueError("Invalid code format received from editor")

            operations.pre_code_execution()

            namespace = {}
            try:
                with operations.patch_lazy_constructors():
                    exec(code, namespace)
            except TypeError as error:
                migrated_namespace = operations.migrate_code_namespace(code, error, namespace)
                if migrated_namespace is not None:
                    namespace = migrated_namespace
                else:
                    raise

            if not operations.apply_code_namespace(namespace):
                raise ValueError(payload.missing_error_message)

            operations.post_code_execution()

        except (SyntaxError, Exception) as error:
            import traceback

            full_traceback = traceback.format_exc()
            logger.error(
                "Failed to parse edited %s code: %s\nFull traceback:\n%s",
                code_type,
                error,
                full_traceback,
            )
            raise

    def _resolve_action(
        self,
        operations: ManagerActionOperations,
        action: str,
    ) -> Optional[Callable[..., Any]]:
        if action in operations.dynamic_actions:
            resolver_name = operations.dynamic_actions[action]
            resolved_action_name = operations.resolve_method(resolver_name)()
            return operations.resolve_method(resolved_action_name)

        method_name = operations.action_registry.get(action)
        if method_name is None:
            return None
        return operations.resolve_method(method_name)

    def show_code_editor(
        self,
        *,
        operations: ManagerActionOperations,
        code: str,
        title: str,
        callback: Callable[[str], None],
        code_type: str,
        code_data: dict[str, Any],
    ) -> None:
        from pyqt_reactive.widgets.editors.simple_code_editor import SimpleCodeEditorService

        editor_service = SimpleCodeEditorService(operations.widget)
        use_external = os.environ.get("OPENHCS_USE_EXTERNAL_EDITOR", "").lower() in (
            "1",
            "true",
            "yes",
        )

        editor_service.edit_code(
            initial_content=code,
            title=title,
            callback=callback,
            use_external=use_external,
            code_type=code_type,
            code_data=code_data,
        )
