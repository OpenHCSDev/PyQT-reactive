"""Code documents of ObjectState scopes and managed windows, served from the running Qt UI."""

from __future__ import annotations

from collections.abc import Callable

from formbridge.bridge.contracts import (
    UiBridgeSnapshotProviderABC,
    UiCodeDocumentProviderIdentity,
)
from formbridge.bridge.dto import (
    UiCodeDocumentSummary,
)
from formbridge.bridge.identities import UiStableWindowIdentityDeclaration
from formbridge.bridge.object_state import (
    OBJECT_STATE_SCOPE_CODE_DOCUMENT_ID,
    OBJECT_STATE_SCOPE_CODE_DOCUMENT_PREFIX,
    OBJECT_STATE_SCOPE_PROVIDER_ID,
    WINDOW_CODE_DOCUMENT_ID,
    WINDOW_CODE_DOCUMENT_PREFIX,
    ObjectStateScopeCodeDocumentAddress,
    ObjectStateScopeProvider,
    WindowCodeDocumentAddress,
    WindowCodeDocumentDriverBackedProvider,
    agent_object_state_scope_id,
)
from formbridge.bridge.registry import UiBridgeProviderSetABC, UiBridgeRegistrationContext
from formbridge.contracts import SCHEMA_VERSION
from formbridge.services.function_pattern_code_document import (
    FunctionPatternScopeCodeDocumentDriver,
)
from objectstate import ObjectStateRegistry

from pyqt_reactive.services.scope_window_navigation import ScopeWindowNavigationService
from pyqt_reactive.services.window_manager import WindowManager
from pyqt_reactive.services.window_navigation import WindowNavigationRequest


class ObjectStateScopeCodeDocumentProvider(WindowCodeDocumentDriverBackedProvider):
    """Dynamic code-document provider for WindowManager-backed ObjectState scopes."""

    identity = UiCodeDocumentProviderIdentity(
        document_id=OBJECT_STATE_SCOPE_CODE_DOCUMENT_ID,
        widget_id=OBJECT_STATE_SCOPE_CODE_DOCUMENT_ID,
        title="ObjectState scope code documents",
    )

    def __init__(
        self,
        snapshot_provider: UiBridgeSnapshotProviderABC,
        before_mutation: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(snapshot_provider)
        self._before_mutation = before_mutation

    def _before_apply(self, address: ObjectStateScopeCodeDocumentAddress) -> None:
        if self._before_mutation is not None:
            self._before_mutation(self._scope_id(address))

    def handles(self, document_id: str) -> bool:
        return document_id == self.identity.document_id or document_id.startswith(
            OBJECT_STATE_SCOPE_CODE_DOCUMENT_PREFIX
        )

    def summaries(self) -> tuple[UiCodeDocumentSummary, ...]:
        summaries = tuple(
            self._summary_for_scope_id(scope_id) for scope_id in self._readable_scope_ids()
        )
        if not summaries:
            return (self.summary(),)
        return summaries

    def revision_key_for_document_id(self, document_id: str) -> str:
        return self._revision_key_for_address(self._address(document_id))

    def summary(self) -> UiCodeDocumentSummary:
        return UiCodeDocumentSummary(
            schema_version=SCHEMA_VERSION,
            identity=self.identity.as_document_identity(),
            widget_id=self.identity.widget_id,
            title=(
                "ObjectState scope code documents "
                f"({OBJECT_STATE_SCOPE_CODE_DOCUMENT_PREFIX}<scope_id>)"
            ),
            readable=False,
            writable=False,
            total_scope_count=len(ObjectStateRegistry.get_all()),
        )

    def _readable_scope_ids(self) -> tuple[str, ...]:
        return tuple(
            agent_object_state_scope_id(state.scope_id) or state.scope_id
            for state in ObjectStateRegistry.get_all()
            if self._has_code_document_driver(state.scope_id)
        )

    def _has_code_document_driver(self, scope_id: str) -> bool:
        if FunctionPatternScopeCodeDocumentDriver.handles_scope(scope_id):
            return True
        code_document_scopes = WindowManager.get_code_document_scopes()
        window_id = agent_object_state_scope_id(scope_id) or scope_id
        return any(
            candidate_scope_id in code_document_scopes
            for candidate_scope_id in (
                UiStableWindowIdentityDeclaration.manager_scopes_for_window_id(window_id)
            )
        )

    def _summary_for_scope_id(self, scope_id: str) -> UiCodeDocumentSummary:
        address = ObjectStateScopeCodeDocumentAddress(scope_id=scope_id)
        title = self._title_for_scope_id(scope_id)
        return self._summary_for_address(address, title)

    def _title_for_scope_id(self, scope_id: str) -> str:
        for candidate_scope_id in UiStableWindowIdentityDeclaration.manager_scopes_for_window_id(
            scope_id
        ):
            window = WindowManager.get_window(candidate_scope_id)
            if window is not None:
                return f"Code mode - {window.windowTitle()}"
        return f"Code mode - {scope_id}"

    def _address(self, document_id: str) -> ObjectStateScopeCodeDocumentAddress:
        return ObjectStateScopeCodeDocumentAddress.parse(document_id)

    def _driver(self, address: ObjectStateScopeCodeDocumentAddress):
        scope_id = self._scope_id(address)
        if FunctionPatternScopeCodeDocumentDriver.handles_scope(scope_id):
            return FunctionPatternScopeCodeDocumentDriver(scope_id)
        return WindowManager.require_code_document_driver(scope_id)

    def _scope_id(self, address: ObjectStateScopeCodeDocumentAddress) -> str:
        for scope_id in UiStableWindowIdentityDeclaration.manager_scopes_for_window_id(
            address.scope_id
        ):
            if FunctionPatternScopeCodeDocumentDriver.handles_scope(scope_id):
                return scope_id
            try:
                WindowManager.require_code_document_driver(scope_id)
                return scope_id
            except KeyError:
                continue
        for scope_id in UiStableWindowIdentityDeclaration.manager_scopes_for_window_id(
            address.scope_id
        ):
            result = ScopeWindowNavigationService.navigate(
                WindowNavigationRequest(
                    scope_id=scope_id,
                    create_if_missing=True,
                )
            )
            if result.window is not None:
                return scope_id
        raise KeyError(f"ObjectState scope window is not available: {address.scope_id!r}")

    def _summary_for_address(
        self,
        address: ObjectStateScopeCodeDocumentAddress,
        title: str,
    ) -> UiCodeDocumentSummary:
        identity = address.provider_identity(title)
        writable = self._driver(address).writable()
        return UiCodeDocumentSummary(
            schema_version=SCHEMA_VERSION,
            identity=identity.as_document_identity(),
            widget_id=identity.widget_id,
            title=title,
            readable=True,
            writable=writable,
            current_selection_count=1,
            total_scope_count=len(ObjectStateRegistry.get_all()),
        )

    def _selected_scope_ids(
        self,
        address: ObjectStateScopeCodeDocumentAddress,
    ) -> tuple[str, ...]:
        return (address.scope_id,)

    def _revision_key_for_address(
        self,
        address: ObjectStateScopeCodeDocumentAddress,
    ) -> str:
        return address.revision_key

    def _provider_identity_for_label(
        self,
        address: ObjectStateScopeCodeDocumentAddress,
    ) -> UiCodeDocumentProviderIdentity:
        return address.provider_identity(self.identity.title)

    def _mutation_scope_id(self, address: ObjectStateScopeCodeDocumentAddress) -> str:
        return self._scope_id(address)


class WindowManagerCodeDocumentProvider(WindowCodeDocumentDriverBackedProvider):
    """Discover and route live WindowManager code-mode documents."""

    identity = UiCodeDocumentProviderIdentity(
        document_id=WINDOW_CODE_DOCUMENT_ID,
        widget_id=WINDOW_CODE_DOCUMENT_ID,
        title="Open window code-mode documents",
    )

    def handles(self, document_id: str) -> bool:
        return document_id.startswith(WINDOW_CODE_DOCUMENT_PREFIX)

    def revision_key_for_document_id(self, document_id: str) -> str:
        return self._revision_key_for_address(self._address(document_id))

    def summary(self) -> UiCodeDocumentSummary:
        return UiCodeDocumentSummary(
            schema_version=SCHEMA_VERSION,
            identity=self.identity.as_document_identity(),
            widget_id=self.identity.widget_id,
            title=(f"Open window code-mode documents ({WINDOW_CODE_DOCUMENT_PREFIX}<window_id>)"),
            readable=False,
            writable=False,
            total_scope_count=len(WindowManager.get_code_document_scopes()),
        )

    def summaries(self) -> tuple[UiCodeDocumentSummary, ...]:
        scopes = WindowManager.get_code_document_scopes()
        if not scopes:
            return (self.summary(),)
        return tuple(self._summary_for_open_scope(scope_id) for scope_id in scopes)

    def _summary_for_open_scope(self, scope_id: str) -> UiCodeDocumentSummary:
        address = WindowCodeDocumentAddress.from_scope_id(scope_id)
        window = WindowManager.get_window(scope_id)
        title = self._open_scope_title(scope_id, address, window)
        return self._summary_for_address(address, title)

    def _open_scope_title(
        self,
        scope_id: str,
        address: WindowCodeDocumentAddress,
        window,
    ) -> str:
        if window is not None and window.windowTitle():
            return f"Code mode - {window.windowTitle()}"
        try:
            document_title = (
                WindowManager.require_code_document_driver(scope_id).read_document(clean=True).title
            )
        except Exception:
            document_title = address.window_id
        return f"Code mode - {document_title}"

    def _address(self, document_id: str) -> WindowCodeDocumentAddress:
        return WindowCodeDocumentAddress.parse(document_id)

    def _driver(self, address: WindowCodeDocumentAddress):
        return WindowManager.require_code_document_driver(self._scope_id(address))

    def _scope_id(self, address: WindowCodeDocumentAddress) -> str:
        for scope_id in UiStableWindowIdentityDeclaration.manager_scopes_for_window_id(
            address.window_id
        ):
            try:
                WindowManager.require_code_document_driver(scope_id)
                return scope_id
            except KeyError:
                continue
        raise KeyError(f"Open window has no code-document driver registered: {address.window_id!r}")

    def _summary_for_address(
        self,
        address: WindowCodeDocumentAddress,
        title: str,
    ) -> UiCodeDocumentSummary:
        identity = address.provider_identity(title)
        writable = self._driver(address).writable()
        return UiCodeDocumentSummary(
            schema_version=SCHEMA_VERSION,
            identity=identity.as_document_identity(),
            widget_id=identity.widget_id,
            title=title,
            readable=True,
            writable=writable,
            current_selection_count=1,
            total_scope_count=len(WindowManager.get_code_document_scopes()),
        )

    def _selected_scope_ids(
        self,
        address: WindowCodeDocumentAddress,
    ) -> tuple[str, ...]:
        return (self._scope_id(address),)

    def _revision_key_for_address(self, address: WindowCodeDocumentAddress) -> str:
        return address.revision_key

    def _current_revision_token(self, address: WindowCodeDocumentAddress) -> str:
        return self._driver(address).current_revision_token()

    def _provider_identity_for_label(
        self,
        address: WindowCodeDocumentAddress,
    ) -> UiCodeDocumentProviderIdentity:
        return address.provider_identity(self.identity.title)

    def _mutation_scope_id(self, address: WindowCodeDocumentAddress) -> str:
        return self._scope_id(address)


class ObjectStateBridgeProviderSet(UiBridgeProviderSetABC):
    """Provider set for ObjectState registry projections."""

    registry_key = OBJECT_STATE_SCOPE_PROVIDER_ID

    def __init__(
        self,
        before_mutation: Callable[[str], None] | None = None,
    ) -> None:
        self._before_mutation = before_mutation

    @classmethod
    def for_main_window(cls, main_window) -> ObjectStateBridgeProviderSet:
        return cls(main_window.session.require_definition_mutation_allowed_for_object_scope)

    def register(self, context: UiBridgeRegistrationContext) -> None:
        context.registry.register_object_state_scope_provider(ObjectStateScopeProvider())
        context.registry.register_code_document_provider(
            ObjectStateScopeCodeDocumentProvider(
                context.snapshot_provider,
                before_mutation=self._before_mutation,
            )
        )
        context.registry.register_code_document_provider(
            WindowManagerCodeDocumentProvider(context.snapshot_provider)
        )
