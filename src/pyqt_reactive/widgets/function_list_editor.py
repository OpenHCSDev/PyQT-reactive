"""
Function List Editor Widget for PyQt6 GUI.

Mirrors the Textual TUI FunctionListEditorWidget with sophisticated parameter forms.
Displays a scrollable list of function panes with Add/Load/Save/Code controls.
"""

import logging
import os
import copy
from contextlib import contextmanager, nullcontext
from typing import List, Union, Dict, Optional, Any, Callable

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal

from pyqt_reactive.protocols import (
    get_function_registry,
    get_component_selection_provider,
    get_function_selection_provider,
)
from pyqt_reactive.services.pattern_data_manager import PatternDataManager
from pyqt_reactive.services.pattern_data_manager import FUNC_EDITOR_SELECTED_PATTERN_KEY_META_KEY
from pyqt_reactive.services.pattern_data_manager import FUNC_EDITOR_PATTERN_TOKENS_META_KEY
from pyqt_reactive.services.function_navigation import parse_function_field_target
from python_introspect import SignatureAnalyzer
from pyqt_reactive.widgets.function_pane import FunctionPaneWidget
from objectstate import ObjectStateRegistry
from pyqt_reactive.theming import ColorScheme
from pyqt_reactive.theming import StyleSheetGenerator
from pyqt_reactive.forms.layout_constants import CURRENT_LAYOUT
from pyqt_reactive.forms.widget_strategies import _get_enum_display_text

logger = logging.getLogger(__name__)


class FunctionListEditorWidget(QWidget):
    """
    Function list editor widget that mirrors Textual TUI functionality.

    Displays functions with parameter editing, Add/Delete/Reset buttons,
    and Load/Save/Code functionality.
    """

    # Signals
    function_pattern_changed = pyqtSignal()

    # No ObjectState - this widget manages data through function panes, not ParameterFormManager
    state = None
    
    def __init__(self, initial_functions: Union[List, Dict, callable, None] = None,
                  context_identifier: str = None, service_adapter=None, color_scheme: Optional[ColorScheme] = None,
                  scope_id: Optional[str] = None, parent=None, render_header: bool = True,
                  button_style: Optional[str] = None, scope_index: Optional[int] = None):
        super().__init__(parent)

        # Initialize color scheme
        self.color_scheme = color_scheme or ColorScheme()
        self._render_header = render_header
        self.header_label: Optional[QLabel] = None
        self._button_style = button_style  # Store centralized button style
        self.style_generator = StyleSheetGenerator(self.color_scheme)

        # Context configuration properties (mirrors Textual TUI)
        self.current_group_by = None  # Current GroupBy setting from context form
        self.current_variable_components = []  # Current VariableComponents list from context form
        self.selected_pattern_key = None  # Currently selected dict key
        self.available_pattern_keys = []  # Available dict keys (if any)
        self.is_dict_mode = False  # Whether we're in channel-specific mode

        # Time-travel may request a dict-key selection before dict mode is initialized.
        self._pending_selected_pattern_key = None
        self._pattern_event_suppression_depth = 0
        # Sidecar per-occurrence function tokens (never stored in kwargs).
        # List mode: list[str]
        # Dict mode: dict[str, list[str]]
        self._pattern_tokens: Union[List[str], Dict[str, List[str]]] = []
        # Tokens aligned with self.functions for currently visible view.
        self._current_function_tokens: List[str] = []

        # Component selection cache per GroupBy (mirrors Textual TUI)
        self.component_selections = {}

        # Create action buttons container (always, for external access)
        self._action_buttons_container = QWidget()
        self._action_buttons_container.setObjectName("func_action_buttons_container")
        self._action_buttons_layout = QHBoxLayout(self._action_buttons_container)
        self._action_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._action_buttons_layout.setSpacing(2)
        self._action_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        add_btn = QPushButton("Add")
        add_btn.setMaximumWidth(60)
        add_btn.setFixedHeight(CURRENT_LAYOUT.button_height)
        add_btn.setStyleSheet(self._get_button_style())
        add_btn.clicked.connect(self.add_function)
        self._action_buttons_layout.addWidget(add_btn)

        code_btn = QPushButton("Code")
        code_btn.setMaximumWidth(60)
        code_btn.setFixedHeight(CURRENT_LAYOUT.button_height)
        code_btn.setStyleSheet(self._get_button_style())
        code_btn.clicked.connect(self.edit_function_code)
        self._action_buttons_layout.addWidget(code_btn)

        # Component selection button
        self.component_btn = QPushButton(self._get_component_button_text())
        self.component_btn.setMaximumWidth(120)
        self.component_btn.setFixedHeight(CURRENT_LAYOUT.button_height)
        self.component_btn.setStyleSheet(self._get_button_style())
        self.component_btn.clicked.connect(self.show_component_selection_dialog)
        self.component_btn.setEnabled(not self._is_component_button_disabled())
        self._action_buttons_layout.addWidget(self.component_btn)

        # Channel navigation buttons.
        #
        # These are needed in dict mode (component-selected mode) to let the user
        # switch between dict keys/components. When render_header=False (DualEditorWindow
        # embeds the action buttons container in its own header), the nav buttons
        # must still exist and be clickable.
        self.prev_key_btn = QPushButton("<")
        self.prev_key_btn.setMaximumWidth(30)
        self.prev_key_btn.setFixedHeight(CURRENT_LAYOUT.button_height)
        self.prev_key_btn.setStyleSheet(self._get_button_style())
        self.prev_key_btn.clicked.connect(lambda: self._navigate_pattern_key(-1))
        self._action_buttons_layout.addWidget(self.prev_key_btn)

        self.next_key_btn = QPushButton(">")
        self.next_key_btn.setMaximumWidth(30)
        self.next_key_btn.setFixedHeight(CURRENT_LAYOUT.button_height)
        self.next_key_btn.setStyleSheet(self._get_button_style())
        self.next_key_btn.clicked.connect(lambda: self._navigate_pattern_key(1))
        self._action_buttons_layout.addWidget(self.next_key_btn)

        # Initialize services (reuse existing business logic)
        self.function_registry = get_function_registry()
        self.component_selection_provider = get_component_selection_provider()
        self.function_selection_provider = get_function_selection_provider()
        if self.component_selection_provider is None:
            raise RuntimeError("No component selection provider registered. Call register_component_selection_provider(...).")
        if self.function_selection_provider is None:
            raise RuntimeError("No function selection provider registered. Call register_function_selection_provider(...).")
        self._groupby_enum = self.component_selection_provider.get_groupby_enum()
        self.data_manager = PatternDataManager()
        self.service_adapter = service_adapter

        # Context identifier for cache isolation
        self.context_identifier = context_identifier or f"widget_{id(self)}"

        # Store scope_id for cross-window live context updates.
        self.scope_id = scope_id

        # Optional index used for scope border alignment.
        self.scope_index = scope_index

        # Scope color scheme for styling newly created panes
        self._scope_color_scheme = None

        # Initialize pattern data and mode
        self._initialize_pattern_data(initial_functions)

        # UI components
        self.function_panes = []

        self.setup_ui()
        self.setup_connections()

        # Subscribe to ObjectState resolved changes for cross-window updates.
        self._subscribe_to_context_state_changes()

        # Time-travel: refresh function pane widgets after restore
        self._time_travel_callback = None
        self._subscribe_to_time_travel()

        logger.debug(f"Function list editor initialized with {len(self.functions)} functions")

    def _subscribe_to_time_travel(self) -> None:
        """Refresh function pane widgets after time-travel restores ObjectState."""
        if not self.scope_id:
            return

        def _is_relevant_time_travel(dirty_states) -> bool:
            scope = str(self.scope_id)
            for entry in dirty_states or []:
                if not isinstance(entry, (tuple, list)) or len(entry) < 1:
                    continue
                scope_id = entry[0]
                if not isinstance(scope_id, str) or not scope_id:
                    continue
                if scope_id == scope or scope_id.startswith(scope + "::"):
                    return True
            return False

        def on_time_travel_complete(dirty_states, triggering_scope):
            # Time-travel restores can update function ObjectStates without marking them dirty.
            # Refresh all panes to keep UI in sync.
            logger.debug(
                "[FUNC_EDITOR] Time-travel refresh: scope=%s dirty_count=%s",
                self.scope_id,
                len(dirty_states),
            )

            with self._suppress_pattern_events():
                # If the step's func pattern changed (e.g., reorder + undo/redo), reload
                # the list so pane ordering matches the restored pattern.
                if _is_relevant_time_travel(dirty_states):
                    self._refresh_pattern_from_context_state()

                from PyQt6 import sip

                for pane in list(self.function_panes):
                    if sip.isdeleted(pane):
                        continue
                    fm = pane.form_manager
                    if fm is not None:
                        fm.refresh_widgets_from_state()

                # Re-apply current pattern so kwargs are pushed to panes
                self.refresh_from_context()

                # Restore visible dict-pattern key from metadata only if current
                # key is no longer valid.
                self.apply_selected_pattern_key_from_state()

        ObjectStateRegistry.add_time_travel_complete_callback(on_time_travel_complete)
        self._time_travel_callback = on_time_travel_complete

        def cleanup_subscription():
            if self._time_travel_callback:
                ObjectStateRegistry.remove_time_travel_complete_callback(self._time_travel_callback)
                self._time_travel_callback = None

        self.destroyed.connect(cleanup_subscription)

    def _get_context_state(self):
        """Return the context ObjectState for this editor."""
        return ObjectStateRegistry.get_by_scope(str(self.scope_id))

    def _record_selected_pattern_key(self) -> None:
        """Persist the currently visible dict-pattern key in ObjectState.metadata."""
        if not self.is_dict_mode:
            return
        if self.selected_pattern_key is None:
            return
        state = self._get_context_state()
        if state is None:
            return
        state.metadata[FUNC_EDITOR_SELECTED_PATTERN_KEY_META_KEY] = str(self.selected_pattern_key)

    def apply_selected_pattern_key_from_state(self) -> None:
        """Apply dict-pattern key from ObjectState metadata.

        Invariant: if current key is still valid, keep it. Metadata only selects
        a key when no valid current selection exists.
        """
        state = self._get_context_state()
        if state is None:
            return
        key = state.metadata.get(FUNC_EDITOR_SELECTED_PATTERN_KEY_META_KEY)
        if key is None:
            return

        key = str(key)
        if not self.is_dict_mode or not isinstance(self.pattern_data, dict):
            self._pending_selected_pattern_key = key
            return
        if (
            self.selected_pattern_key is not None
            and str(self.selected_pattern_key) in self.pattern_data
        ):
            return
        if key not in self.pattern_data:
            return

        # Time-travel/UI restore path: DO NOT save current functions into pattern_data.
        # pattern_data is authoritative from ObjectState; we just need to update the view.
        self._select_pattern_key(
            key,
            commit_current_view=False,
            persist_selection=False,
        )

    def _load_pattern_tokens_from_state(self) -> None:
        """Load persisted per-occurrence tokens from context ObjectState metadata."""
        state = self._get_context_state()
        if state is None:
            self._pattern_tokens = []
            return
        raw = state.metadata.get(FUNC_EDITOR_PATTERN_TOKENS_META_KEY)
        if isinstance(raw, list):
            self._pattern_tokens = [str(token) for token in raw if token]
            return
        if isinstance(raw, dict):
            normalized: Dict[str, List[str]] = {}
            for channel_key, tokens in raw.items():
                if not isinstance(tokens, list):
                    continue
                normalized[str(channel_key)] = [str(token) for token in tokens if token]
            self._pattern_tokens = normalized
            return
        self._pattern_tokens = []

    def _persist_pattern_tokens_to_state(self) -> None:
        """Persist per-occurrence tokens in context ObjectState metadata."""
        state = self._get_context_state()
        if state is None:
            return
        state.metadata[FUNC_EDITOR_PATTERN_TOKENS_META_KEY] = copy.deepcopy(
            self._pattern_tokens
        )

    @staticmethod
    def _sanitize_pattern_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate kwargs and reject internal scope-token metadata."""
        from pyqt_reactive.services.pattern_data_manager import SCOPE_TOKEN_KEY

        if not isinstance(kwargs, dict):
            return {}
        if SCOPE_TOKEN_KEY in kwargs:
            raise RuntimeError(
                "Function kwargs contain internal scope-token metadata. "
                "Tokens must be stored in ObjectState metadata."
            )
        return dict(kwargs)

    def _get_tokens_for_current_view(self) -> List[str]:
        if self.is_dict_mode and isinstance(self._pattern_tokens, dict):
            key = str(self.selected_pattern_key) if self.selected_pattern_key is not None else ""
            return list(self._pattern_tokens.get(key, []))
        if isinstance(self._pattern_tokens, list):
            return list(self._pattern_tokens)
        return []

    def _set_tokens_for_current_view(self, tokens: List[str]) -> None:
        normalized = [str(token) for token in tokens if token]
        if self.is_dict_mode:
            if not isinstance(self._pattern_tokens, dict):
                self._pattern_tokens = {}
            key = str(self.selected_pattern_key) if self.selected_pattern_key is not None else ""
            self._pattern_tokens[key] = normalized
        else:
            self._pattern_tokens = normalized

    def _select_pattern_key(
        self,
        key: str,
        *,
        commit_current_view: bool,
        persist_selection: bool,
    ) -> None:
        """Select dict-pattern key using one invariant code path."""
        if not self.is_dict_mode or not isinstance(self.pattern_data, dict):
            return
        if key not in self.pattern_data:
            return

        if self.selected_pattern_key == key:
            if persist_selection:
                self._record_selected_pattern_key()
            self._refresh_component_button()
            self._update_navigation_buttons()
            return

        if commit_current_view:
            self._update_pattern_data()

        self.selected_pattern_key = key
        if persist_selection:
            self._record_selected_pattern_key()

        self.functions = self.pattern_data.get(key, [])
        if isinstance(self._pattern_tokens, dict):
            self._current_function_tokens = list(self._pattern_tokens.get(key, []))
        else:
            self._current_function_tokens = []

        self._refresh_component_button()
        self._populate_function_list()
        self._update_navigation_buttons()

    def _refresh_pattern_from_context_state(self) -> None:
        """Reload the function pattern from the context ObjectState.

        Undo/redo uses ObjectState time-travel. When the `func` parameter
        changes (e.g. reorder), the editor must rebuild panes to match the
        restored order.
        """
        if not self.scope_id:
            return

        state = ObjectStateRegistry.get_by_scope(str(self.scope_id))
        if state is None:
            return

        if "func" not in state.parameters:
            return

        func_pattern = state.parameters.get("func")
        if func_pattern is None:
            func_pattern = []

        # Clone to avoid mutating the ObjectState-owned pattern in-place.
        func_pattern = PatternDataManager.clone_pattern(func_pattern)

        # Capture existing panes by token so we can reorder without destroying widgets.
        pane_by_token: dict[str, Any] = {}
        for pane in list(self.function_panes):
            token = getattr(pane, "func_scope_token", None)
            if token:
                pane_by_token[str(token)] = pane

        prev_selected = self.selected_pattern_key
        prev_dict_mode = self.is_dict_mode

        # Do not apply any pending UI selection during a time-travel refresh.
        # The authoritative selection comes from ObjectState.metadata.
        self._pending_selected_pattern_key = None

        self._initialize_pattern_data(func_pattern)

        # Time-travel must restore the visible dict-pattern key from ObjectState.metadata.
        # If no metadata exists (or key is invalid), fall back to preserving prior selection.
        restored_key = None
        if self.is_dict_mode and isinstance(self.pattern_data, dict):
            restored_key = state.metadata.get(FUNC_EDITOR_SELECTED_PATTERN_KEY_META_KEY)
            if restored_key is not None:
                restored_key = str(restored_key)
                if restored_key in self.pattern_data:
                    self.selected_pattern_key = restored_key
                    self.functions = self.pattern_data.get(restored_key, [])
                    if isinstance(self._pattern_tokens, dict):
                        self._current_function_tokens = list(
                            self._pattern_tokens.get(restored_key, [])
                        )
                else:
                    restored_key = None

        if (
            restored_key is None
            and prev_dict_mode
            and self.is_dict_mode
            and prev_selected
            and isinstance(self.pattern_data, dict)
            and prev_selected in self.pattern_data
        ):
            self.selected_pattern_key = prev_selected
            self.functions = self.pattern_data.get(prev_selected, [])
            if isinstance(self._pattern_tokens, dict):
                self._current_function_tokens = list(
                    self._pattern_tokens.get(prev_selected, [])
                )

        # Fast path: if this is only a reorder (same tokens/functions), move panes in-place.
        new_tokens: list[str] = list(self._current_function_tokens)
        expected_func_by_token: dict[str, Any] = {}
        if len(new_tokens) != len(self.functions):
            new_tokens = []
        for index, item in enumerate(self.functions):
            func, _kwargs = PatternDataManager.extract_func_and_kwargs(item)
            if func is None:
                new_tokens = []
                break
            token = str(new_tokens[index]) if index < len(new_tokens) else ""
            if not token:
                new_tokens = []
                break
            expected_func_by_token[token] = func

        from PyQt6 import sip

        can_reorder = (
            self.function_panes
            and all(not sip.isdeleted(p) for p in self.function_panes)
            and len(new_tokens) == len(self.function_panes)
            and len(set(new_tokens)) == len(new_tokens)
            and len(pane_by_token) == len(self.function_panes)
            and all(not sip.isdeleted(p) for p in pane_by_token.values())
            and set(new_tokens) == set(pane_by_token.keys())
        )
        if can_reorder:
            for token in new_tokens:
                pane = pane_by_token.get(token)
                if pane is None or getattr(pane, "func", None) is not expected_func_by_token.get(token):
                    can_reorder = False
                    break

        if can_reorder:
            self.function_panes = [pane_by_token[t] for t in new_tokens]
            for i, pane in enumerate(self.function_panes):
                pane.index = i

            # Reorder widgets in layout without recreating them.
            for i, pane in enumerate(self.function_panes):
                self.function_layout.insertWidget(i, pane)
        else:
            # Fallback for add/remove/replace: rebuild panes.
            self._populate_function_list()

        self._refresh_component_button()
        self._update_navigation_buttons()

    def _initialize_pattern_data(self, initial_functions):
        """Initialize pattern data from various input formats (mirrors Textual TUI logic)."""
        # Load persisted sidecar tokens and seed generator so new tokens never collide.
        self._load_pattern_tokens_from_state()
        self._seed_func_token_generator()
        if initial_functions is None:
            self.pattern_data = []
            self._pattern_tokens = []
            self.is_dict_mode = False
            self.functions = []
            self._current_function_tokens = []
        elif callable(initial_functions):
            # Single callable: treat as [(callable, {})]
            token = self._get_func_token_generator().ensure()
            self.pattern_data = [(initial_functions, {})]
            self._pattern_tokens = [token]
            self.is_dict_mode = False
            self.functions = list(self.pattern_data)
            self._current_function_tokens = [token]
        elif isinstance(initial_functions, tuple) and len(initial_functions) == 2 and callable(initial_functions[0]) and isinstance(initial_functions[1], dict):
            # Single tuple (callable, kwargs): treat as [(callable, kwargs)]
            func, kwargs = initial_functions
            clean_kwargs = self._sanitize_pattern_kwargs(kwargs)
            token = self._get_func_token_generator().ensure()
            self.pattern_data = [(func, clean_kwargs)]
            self._pattern_tokens = [str(token)]
            self.is_dict_mode = False
            self.functions = list(self.pattern_data)
            self._current_function_tokens = [str(token)]
        elif isinstance(initial_functions, list):
            seen_tokens: set[str] = set()
            self.is_dict_mode = False
            seed_tokens = self._pattern_tokens if isinstance(self._pattern_tokens, list) else []
            self.functions, tokens = self._normalize_function_list(
                initial_functions,
                seen_tokens=seen_tokens,
                seed_tokens=seed_tokens,
            )
            self._pattern_tokens = list(tokens)
            self._current_function_tokens = list(tokens)
            self.pattern_data = list(self.functions)
        elif isinstance(initial_functions, dict):
            # Convert any integer keys to string keys for consistency
            seen_tokens: set[str] = set()
            normalized_dict = {}
            normalized_tokens: Dict[str, List[str]] = {}
            existing_tokens = self._pattern_tokens if isinstance(self._pattern_tokens, dict) else {}
            for key, value in initial_functions.items():
                str_key = str(key)
                normalized_list, channel_tokens = (
                    self._normalize_function_list(
                        value,
                        seen_tokens=seen_tokens,
                        seed_tokens=existing_tokens.get(str_key, []),
                    )
                    if value
                    else ([], [])
                )
                normalized_dict[str_key] = normalized_list
                normalized_tokens[str_key] = channel_tokens

            self.pattern_data = normalized_dict
            self._pattern_tokens = normalized_tokens
            self.is_dict_mode = True

            # Set selected channel to first key and load its functions
            if normalized_dict:
                self.selected_pattern_key = next(iter(normalized_dict.keys()))
                self.functions = normalized_dict[self.selected_pattern_key]
                self._current_function_tokens = list(
                    normalized_tokens.get(self.selected_pattern_key, [])
                )
            else:
                self.selected_pattern_key = None
                self.functions = []
                self._current_function_tokens = []
        else:
            logger.warning(f"Unknown initial_functions type: {type(initial_functions)}")
            self.pattern_data = []
            self._pattern_tokens = []
            self.is_dict_mode = False
            self.functions = []
            self._current_function_tokens = []

        self._persist_pattern_tokens_to_state()
        self._apply_pending_pattern_key_selection()

    def _normalize_function_list(
        self,
        func_list,
        *,
        seen_tokens: Optional[set[str]] = None,
        seed_tokens: Optional[List[str]] = None,
    ):
        """Normalize function list using PatternDataManager.

        Ensures every entry is a (callable, kwargs) tuple and returns a parallel
        stable per-entry token list stored in ObjectState metadata.
        """
        if seen_tokens is None:
            seen_tokens = set()
        if seed_tokens is None:
            seed_tokens = []
        # Handle single tuple (function, kwargs) case - wrap in list
        if isinstance(func_list, tuple) and len(func_list) == 2 and callable(func_list[0]) and isinstance(func_list[1], dict):
            func_list = [func_list]
        # Handle single callable case - wrap in list with empty kwargs
        elif callable(func_list):
            func_list = [(func_list, {})]
        # Handle empty or None case
        elif not func_list:
            return [], []

        normalized = []
        tokens: List[str] = []
        for i, item in enumerate(func_list):
            func, kwargs = self.data_manager.extract_func_and_kwargs(item)
            if func:
                new_kwargs = self._sanitize_pattern_kwargs(kwargs if isinstance(kwargs, dict) else {})
                seed_token = str(seed_tokens[i]) if i < len(seed_tokens) and seed_tokens[i] else None
                token = seed_token or self._get_func_token_generator().ensure()
                if token in seen_tokens:
                    token = self._get_func_token_generator().ensure()
                seen_tokens.add(token)
                normalized.append((func, new_kwargs))
                tokens.append(str(token))
        return normalized, tokens

    def _get_function_state_parent_scope(self, channel_key: Optional[str]) -> Optional[str]:
        """Return the parent scope used for function ObjectStates.

        Function parameter ObjectStates must be stable across:
        - reordering
        - switching dict/list pattern modes
        - multiple identical callables in the pattern

        We keep all function states directly under the context scope and rely on a
        per-entry sidecar token stored in metadata for uniqueness.
        """
        if not self.scope_id:
            return None

        return str(self.scope_id)

    def _get_current_function_state_parent_scope(self) -> Optional[str]:
        """Return function ObjectState parent scope for current view."""
        if self.is_dict_mode:
            return self._get_function_state_parent_scope(self.selected_pattern_key)
        return self._get_function_state_parent_scope(None)

    def _unregister_function_states_for_functions(
        self,
        func_items: List[Any],
        channel_key: Optional[str],
        tokens: Optional[List[str]] = None,
    ) -> None:
        """Unregister function ObjectStates for a list of function items."""
        if not self.scope_id or not func_items:
            return

        parent_scope = self._get_function_state_parent_scope(channel_key)
        if not parent_scope:
            return

        for idx, item in enumerate(func_items):
            func, kwargs = PatternDataManager.extract_func_and_kwargs(item)
            if func is None:
                continue

            token = None
            if tokens is not None and idx < len(tokens):
                token = tokens[idx]
            if not token:
                raise RuntimeError(
                    "Missing function scope token while unregistering function state."
                )
            scope = f"{parent_scope}::{token}"
            state = ObjectStateRegistry.get_by_scope(scope)
            if state is not None:
                ObjectStateRegistry.unregister(state)

    @staticmethod
    def _iter_tokenized_entries(
        pattern: Any, tokens: Any
    ) -> List[tuple[Any, Dict[str, Any], str]]:
        """Return flat (func, kwargs, token) entries from pattern + sidecar token map."""
        entries: List[tuple[Any, Dict[str, Any], str]] = []
        if isinstance(pattern, dict):
            token_map = tokens if isinstance(tokens, dict) else {}
            for channel_key, items in pattern.items():
                channel_items = items if isinstance(items, list) else [items]
                channel_tokens = token_map.get(str(channel_key), [])
                for idx, item in enumerate(channel_items):
                    func, kwargs = PatternDataManager.extract_func_and_kwargs(item)
                    if func is None:
                        continue
                    token = (
                        str(channel_tokens[idx])
                        if idx < len(channel_tokens) and channel_tokens[idx]
                        else ""
                    )
                    entries.append((func, dict(kwargs or {}), token))
            return entries

        item_list = pattern if isinstance(pattern, list) else [pattern]
        token_list = tokens if isinstance(tokens, list) else []
        for idx, item in enumerate(item_list):
            func, kwargs = PatternDataManager.extract_func_and_kwargs(item)
            if func is None:
                continue
            token = str(token_list[idx]) if idx < len(token_list) and token_list[idx] else ""
            entries.append((func, dict(kwargs or {}), token))
        return entries

    def _get_func_token_generator(self):
        """Generator for stable per-entry function tokens."""
        from pyqt_reactive.services.scope_token_service import ScopeTokenGenerator

        gen = getattr(self, "_func_token_generator", None)
        if gen is None:
            gen = ScopeTokenGenerator("func", attr_name=None)
            setattr(self, "_func_token_generator", gen)
        return gen

    def _seed_func_token_generator(self) -> None:
        """Seed token generator from canonical sidecar metadata tokens."""
        gen = self._get_func_token_generator()
        tokens: List[str] = []
        if isinstance(self._pattern_tokens, list):
            tokens.extend(str(token) for token in self._pattern_tokens if token)
        elif isinstance(self._pattern_tokens, dict):
            for channel_tokens in self._pattern_tokens.values():
                tokens.extend(str(token) for token in channel_tokens if token)
        if tokens:
            gen.seed_from_tokens(tokens)

    def _apply_pending_pattern_key_selection(self) -> None:
        """Apply pending dict-pattern key selection if possible."""
        channel = self._pending_selected_pattern_key
        if channel is None:
            return
        if not self.is_dict_mode:
            return
        if not isinstance(self.pattern_data, dict):
            return
        if channel not in self.pattern_data:
            return

        self._pending_selected_pattern_key = None
        self._select_pattern_key(
            channel,
            commit_current_view=True,
            persist_selection=True,
        )

    def setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Header with controls (only if render_header=True)
        if self._render_header:
            header_layout = QHBoxLayout()
            
            # Store as instance attribute for scope accent styling
            self.header_label = QLabel("Functions")
            self.header_label.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_accent)}; font-weight: bold; font-size: 14px;")
            header_layout.addWidget(self.header_label)
            
            header_layout.addStretch()
            
            # Add action buttons to header
            header_layout.addWidget(self._action_buttons_container)
            
            header_layout.addStretch()
            layout.addLayout(header_layout)
        else:
            # Header not rendered - buttons remain in _action_buttons_container for external use
            pass

        # Ensure nav buttons are shown/hidden correctly for the initial pattern.
        self._update_navigation_buttons()

        
        # Scrollable function list (mirrors Textual TUI)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.panel_bg)};
                border: 1px solid {self.color_scheme.to_hex(self.color_scheme.border_color)};
                border-radius: 4px;
            }}
        """)
        
        # Function list container
        self.function_container = QWidget()
        self.function_layout = QVBoxLayout(self.function_container)
        self.function_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.function_layout.setSpacing(8)
        
        # Populate function list
        self._populate_function_list()
        
        self.scroll_area.setWidget(self.function_container)
        layout.addWidget(self.scroll_area)

    def select_and_scroll_to_field(self, field_path: str) -> None:
        """Public API for WindowManager navigation protocol.

        The step editor uses this to navigate to the function-pattern UI after
        time-travel/provenance actions.

        Supported targets:
        - "func" (or any "func...") : scroll to the function list and flash the
          first pane (if any)
        - "func.<index>" / "func[<index>]" : scroll to that function pane (best-effort)
        """

        logger.debug("[SCROLL] FunctionListEditorWidget.select_and_scroll_to_field(%r)", field_path)
        if not field_path:
            return
        if self.scroll_area is None:
            return

        target = parse_function_field_target(field_path)
        if target.token:
            self.select_pattern_key_for_function_token(target.token)
        index = target.index

        # Default target: top of the list.
        target_pane: Optional[QWidget] = None
        if isinstance(index, int) and 0 <= index < len(self.function_panes):
            target_pane = self.function_panes[index]
        elif self.function_panes:
            target_pane = self.function_panes[0]

        if target_pane is not None:
            # Ensure the pane is visible within the scroll viewport.
            self.scroll_area.ensureWidgetVisible(target_pane, 0, 20)

            # Flash the pane for local feedback.
            flash_key = getattr(target_pane, "_flash_key", None)
            if flash_key and hasattr(target_pane, "queue_flash_local"):
                target_pane.queue_flash_local(flash_key)  # type: ignore[attr-defined]
        else:
            # No panes (empty state): just move to top.
            self.scroll_area.verticalScrollBar().setValue(0)

        # Invalidate flash overlay geometry cache after programmatic scroll.
        from pyqt_reactive.animation import WindowFlashOverlay

        WindowFlashOverlay.invalidate_cache_for_widget(self)  # type: ignore[arg-type]
    
    def _get_button_style(self) -> str:
        """Get consistent button styling."""
        if self._button_style:
            return self.style_generator.generate_config_button_styles().get(self._button_style, "")

        return f"""
            QPushButton {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.input_bg)};
                color: white;
                border: none;
                border-radius: 3px;
                padding: 6px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.button_hover_bg)};
            }}
            QPushButton:pressed {{
                background-color: {self.color_scheme.to_hex(self.color_scheme.button_pressed_bg)};
            }}
        """
    
    def _populate_function_list(self):
        """Populate function list with panes (mirrors Textual TUI)."""
        # NOTE: We do NOT destroy function ObjectStates or clear scope tokens here.
        # - For code mode: _update_function_object_states() updates existing ObjectStates
        #   with new kwargs BEFORE this method is called, preserving dirty detection.
        # - FunctionPaneWidget.create_parameter_form() reuses existing ObjectStates
        #   (line 297-302 in function_pane.py) if they exist.
        # - ObjectStates for removed functions are cleaned up when their widgets are destroyed.
        # - Scope tokens must persist so build_scope_id returns the same scope_id for
        #   the same function object, allowing ObjectState lookup to succeed.

        # Clear existing widgets.
        # IMPORTANT: Only delete via the layout traversal to avoid double-deleting
        # the same FunctionPaneWidget (which crashes with "wrapped C/C++ object ... deleted").
        from PyQt6 import sip

        self.function_panes.clear()
        while self.function_layout.count():
            child = self.function_layout.takeAt(0)
            widget = child.widget()
            if widget is None or sip.isdeleted(widget):
                continue

            # Unregister form manager if it exists
            if isinstance(widget, FunctionPaneWidget) and widget.form_manager is not None:
                widget.form_manager.unregister_from_cross_window_updates()

            widget.deleteLater()  # Schedule for deletion instead of just orphaning
        
        func_scope_prefix = self._get_current_function_state_parent_scope()

        if not self.functions:
            # Show empty state
            empty_label = QLabel("No functions defined. Click 'Add' to begin.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"color: {self.color_scheme.to_hex(self.color_scheme.text_disabled)}; font-style: italic; padding: 20px;")
            self.function_layout.addWidget(empty_label)
        else:
            # Create function panes
            for i, func_item in enumerate(self.functions):
                if i >= len(self._current_function_tokens):
                    self._current_function_tokens.append(self._get_func_token_generator().ensure())
                    self._set_tokens_for_current_view(self._current_function_tokens)
                    self._persist_pattern_tokens_to_state()
                pane = FunctionPaneWidget(
                    func_item,
                    i,
                    self.service_adapter,
                    color_scheme=self.color_scheme,
                    scope_id=self.scope_id,
                    func_scope_prefix=func_scope_prefix,
                    func_scope_token=self._current_function_tokens[i],
                    scope_index=self.scope_index,
                )

                # Connect signals (using actual FunctionPaneWidget signal names)
                pane.move_function.connect(self._move_function)
                pane.add_function.connect(self._add_function_at_index)
                pane.remove_function.connect(self._remove_function)
                pane.parameter_changed.connect(self._on_parameter_changed, type=Qt.ConnectionType.DirectConnection)

                self.function_panes.append(pane)
                self.function_layout.addWidget(pane)

                # Note: Scope color scheme will be applied to all panes
                # in set_scope_color_scheme() which is called after panes are created.
                # This avoids duplicate styling calls.

                # CRITICAL FIX: Apply initial enabled styling for function panes
                # This ensures that when a function pattern editor opens, disabled functions
                # show as correct dimmed styling immediately, not just after toggling
                if pane.form_manager is not None:
                    # Use QTimer to ensure this runs after the widget is fully constructed
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda p=pane: self._apply_initial_enabled_styling_to_pane(p))

        # Apply scope styling to all child widgets (GroupBoxWithHelp, HelpButton, etc.)
        # This must be done AFTER all panes are created so findChildren() finds them all
        if self._scope_color_scheme:
            # Apply immediately for sync-created widgets
            for pane in self.function_panes:
                pane.set_scope_color_scheme(self._scope_color_scheme)
            self._apply_scope_styling_to_children(self._scope_color_scheme)

            # CRITICAL: Register callback on each pane's form_manager for async-created widgets
            # This hooks into FormBuildOrchestrator's async completion system properly
            for pane in self.function_panes:
                if pane.form_manager is not None:
                    # Capture scheme in closure
                    scheme = self._scope_color_scheme
                    pane.form_manager._on_build_complete_callbacks.append(
                        lambda s=scheme: self._apply_scope_styling_to_children(s)
                    )

    def _apply_initial_enabled_styling_to_pane(self, pane):
        """Apply initial enabled styling to a function pane.

        This is called after a function pane is created to ensure that disabled functions
        show the correct dimmed styling immediately when the function pattern editor opens.

        Args:
            pane: FunctionPaneWidget instance to apply styling to
        """
        try:
            if pane.form_manager is not None:
                # Check if the form manager has an enabled field
                if 'enabled' in pane.form_manager.parameters:
                    # CRITICAL FIX: Call the service method, not a non-existent manager method
                    pane.form_manager._enabled_field_styling_service.apply_initial_enabled_styling(pane.form_manager)
        except Exception as e:
            # Log error but don't crash the UI
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to apply initial enabled styling to function pane: {e}")


    def setup_connections(self):
        """Setup signal/slot connections."""
        pass

    @contextmanager
    def _suppress_pattern_events(self):
        """Temporarily suppress outward pattern-change emissions."""
        self._pattern_event_suppression_depth += 1
        try:
            yield
        finally:
            self._pattern_event_suppression_depth -= 1

    def _emit_pattern_changed(self) -> None:
        if self._pattern_event_suppression_depth > 0:
            return
        self.function_pattern_changed.emit()

    def _commit_pattern_mutation(
        self,
        *,
        mutation_label: Optional[str],
        mutate: Callable[[], None],
        refresh_ui: Optional[Callable[[], None]] = None,
        persist_selected_key: bool = True,
    ) -> None:
        """Apply one pattern mutation through a single synchronization path."""
        ctx = (
            ObjectStateRegistry.atomic(mutation_label)
            if mutation_label is not None
            else nullcontext()
        )
        with ctx:
            if persist_selected_key:
                self._record_selected_pattern_key()
            mutate()
            self._update_pattern_data()
            if refresh_ui is not None:
                refresh_ui()
            self._emit_pattern_changed()
    
    def add_function(self):
        """Add a new function (mirrors Textual TUI)."""
        # Show function selector dialog via provider
        selected_function = self.function_selection_provider.select_function(parent=self)

        if selected_function:
            def mutate() -> None:
                new_func_item = (selected_function, {})
                self.functions.append(new_func_item)
                self._current_function_tokens.append(
                    self._get_func_token_generator().ensure()
                )

            self._commit_pattern_mutation(
                mutation_label="add function",
                mutate=mutate,
                refresh_ui=self._populate_function_list,
            )
            logger.debug(f"Added function: {selected_function.__name__}")
    

    
    def edit_function_code(self):
        """Edit function pattern as code (simple and direct)."""
        logger.debug("Edit function code clicked - opening code editor")

        # Validation guard: Check for empty patterns
        if not self.functions and not self.pattern_data:
            if self.service_adapter:
                self.service_adapter.show_info_dialog("No function pattern to edit. Add functions first.")
            return

        try:
            # Update pattern data first
            self._update_pattern_data()

            # Generate complete Python code with imports
            python_code = self._generate_complete_python_code()

            # Create simple code editor service
            from pyqt_reactive.widgets.editors.simple_code_editor import SimpleCodeEditorService
            editor_service = SimpleCodeEditorService(self)

            # Check if user wants external editor (check environment variable)
            use_external = os.environ.get('OPENHCS_USE_EXTERNAL_EDITOR', '').lower() in ('1', 'true', 'yes')

            # Launch editor with callback and code_type for clean mode toggle
            editor_service.edit_code(
                initial_content=python_code,
                title="Edit Function Pattern",
                callback=self._handle_edited_pattern,
                use_external=use_external,
                code_type='function',
                code_data={'pattern_data': self.pattern_data, 'clean_mode': False}
            )

        except Exception as e:
            logger.error(f"Failed to launch code editor: {e}")
            if self.service_adapter:
                self.service_adapter.show_error_dialog(f"Failed to launch code editor: {str(e)}")

    def _generate_complete_python_code(self) -> str:
        """Generate complete Python code with imports (following debug module approach)."""
        # Use complete function pattern code generation from registered provider
        from pyqt_reactive.protocols import get_codegen_provider
        provider = get_codegen_provider()
        if provider is None:
            raise RuntimeError("No codegen provider registered. Call register_codegen_provider(...).")

        # Disable clean_mode to preserve all parameters when same function appears multiple times
        # This prevents parsing issues when the same function has different parameter sets
        return provider.generate_complete_function_pattern_code(self.pattern_data, clean_mode=False)

    def _handle_edited_pattern(self, edited_code: str) -> None:
        """Handle the edited pattern code from code editor."""
        try:
            # Ensure we have a string
            if not isinstance(edited_code, str):
                logger.error(f"Expected string, got {type(edited_code)}: {edited_code}")
                raise ValueError("Invalid code format received from editor")

            # CRITICAL FIX: Execute code with lazy dataclass constructor patching to preserve None vs concrete distinction
            namespace = {}
            with self._patch_lazy_constructors():
                exec(edited_code, namespace)

            # Get the pattern from the namespace
            if 'pattern' in namespace:
                new_pattern = namespace['pattern']
                self._apply_edited_pattern(new_pattern)
            else:
                raise ValueError("No 'pattern = ...' assignment found in edited code")

        except (SyntaxError, Exception) as e:
            logger.error(f"Failed to parse edited pattern: {e}")
            # Re-raise so the code editor can handle it (keep dialog open, move cursor to error line)
            raise

    def _apply_edited_pattern(self, new_pattern):
        """Apply the edited pattern back to the UI."""
        from objectstate import ObjectStateRegistry

        # ATOMIC: Coalesce all register + edit snapshots into single "code edit" snapshot
        # Without this, code mode creates multiple snapshots (one per function register + edit func)
        with ObjectStateRegistry.atomic("code edit"):
            self._apply_edited_pattern_internal(new_pattern)

    def _apply_edited_pattern_internal(self, new_pattern):
        """Internal implementation of apply_edited_pattern (wrapped in atomic block)."""
        try:
            self._seed_func_token_generator()
            old_entries = self._iter_tokenized_entries(
                self.pattern_data, self._pattern_tokens
            )

            # Get the new function list BEFORE updating self.functions
            if self.is_dict_mode:
                if isinstance(new_pattern, dict):
                    # Normalize whole dict so all keys have stable per-entry tokens.
                    seen_tokens: set[str] = set()
                    normalized_pattern: dict[str, list] = {}
                    normalized_tokens: Dict[str, List[str]] = {}
                    seed_by_channel = (
                        self._pattern_tokens if isinstance(self._pattern_tokens, dict) else {}
                    )
                    for k, v in new_pattern.items():
                        sk = str(k)
                        normalized_list, token_list = (
                            self._normalize_function_list(
                                v,
                                seen_tokens=seen_tokens,
                                seed_tokens=seed_by_channel.get(sk, []),
                            )
                            if v
                            else ([], [])
                        )
                        normalized_pattern[sk] = normalized_list
                        normalized_tokens[sk] = token_list
                    new_pattern = normalized_pattern

                    if self.selected_pattern_key and self.selected_pattern_key in new_pattern:
                        new_functions = list(new_pattern[self.selected_pattern_key])
                        new_current_tokens = list(
                            normalized_tokens.get(self.selected_pattern_key, [])
                        )
                    elif new_pattern:
                        new_channel = next(iter(new_pattern))
                        new_functions = list(new_pattern[new_channel])
                        new_current_tokens = list(normalized_tokens.get(new_channel, []))
                    else:
                        new_functions = []
                        new_current_tokens = []
                else:
                    raise ValueError("Expected dict pattern for dict mode")
            else:
                seed_tokens = (
                    self._pattern_tokens if isinstance(self._pattern_tokens, list) else []
                )
                if isinstance(new_pattern, list):
                    new_functions, new_current_tokens = self._normalize_function_list(
                        new_pattern,
                        seed_tokens=seed_tokens,
                    )
                elif callable(new_pattern):
                    new_functions = [(new_pattern, {})]
                    new_current_tokens = [self._get_func_token_generator().ensure()]
                elif isinstance(new_pattern, tuple) and len(new_pattern) == 2 and callable(new_pattern[0]) and isinstance(new_pattern[1], dict):
                    func, kwargs = new_pattern
                    new_functions = [(func, self._sanitize_pattern_kwargs(kwargs))]
                    new_current_tokens = [self._get_func_token_generator().ensure()]
                else:
                    raise ValueError(f"Expected list, callable, or (callable, dict) tuple pattern for list mode, got {type(new_pattern)}")

            # CRITICAL FIX: Update existing function ObjectStates with new kwargs BEFORE
            # creating new widgets. This preserves dirty detection - the ObjectState's
            # saved baseline stays the same, only the current values change.
            if self.is_dict_mode:
                new_entries = self._iter_tokenized_entries(new_pattern, normalized_tokens)
            else:
                new_entries = self._iter_tokenized_entries(new_functions, new_current_tokens)
            self._update_function_object_states(old_entries, new_entries)

            # Now update pattern_data and functions
            if self.is_dict_mode:
                self.pattern_data = new_pattern
                self._pattern_tokens = normalized_tokens
                if self.selected_pattern_key and self.selected_pattern_key in new_pattern:
                    self.functions = new_functions
                elif new_pattern:
                    self.selected_pattern_key = next(iter(new_pattern))
                    self.functions = new_functions
                else:
                    self.functions = []
                self._current_function_tokens = new_current_tokens
            else:
                # Always store normalized list.
                self.pattern_data = list(new_functions)
                self.functions = new_functions
                self._pattern_tokens = list(new_current_tokens)
                self._current_function_tokens = list(new_current_tokens)

            self._persist_pattern_tokens_to_state()

            # Refresh the UI and notify of changes
            # NOTE: _populate_function_list will REUSE ObjectStates that we just updated
            self._populate_function_list()
            self._emit_pattern_changed()

        except Exception as e:
            if self.service_adapter:
                self.service_adapter.show_error_dialog(f"Failed to apply edited pattern: {str(e)}")

    def _update_function_object_states(self, old_entries: List, new_entries: List) -> None:
        """Update existing function ObjectStates with new kwargs from code mode edit.

        This is CRITICAL for dirty detection: instead of destroying and recreating
        ObjectStates (which resets the baseline), we UPDATE existing ones so the
        saved baseline is preserved and changes are detected as dirty.

        Args:
            old_entries: Previous entries [(func, kwargs, token), ...]
            new_entries: New entries from code mode edit
        """
        if not self.scope_id:
            return

        from objectstate import ObjectStateRegistry
        channel_key = self.selected_pattern_key if self.is_dict_mode else None
        parent_scope = self._get_function_state_parent_scope(channel_key) or str(self.scope_id)

        old_by_token: dict[str, tuple[Any, Dict[str, Any]]] = {}
        for func, kwargs, token in old_entries:
            if not token:
                continue
            old_by_token[token] = (func, dict(kwargs or {}))

        new_by_token: dict[str, tuple[Any, Dict[str, Any]]] = {}
        for func, kwargs, token in new_entries:
            if not token:
                continue
            new_by_token[token] = (func, dict(kwargs or {}))

        # Unregister states for removed tokens
        for token in set(old_by_token.keys()) - set(new_by_token.keys()):
            old_func, old_kwargs = old_by_token[token]
            self._unregister_function_states_for_functions(
                [(old_func, old_kwargs)], channel_key, tokens=[token]
            )

        # Update existing states for tokens still present
        for token in set(old_by_token.keys()) & set(new_by_token.keys()):
            old_func, old_kwargs = old_by_token[token]
            new_func, new_kwargs = new_by_token[token]

            # If the function changed but token stayed, treat as replace.
            if old_func is not new_func:
                self._unregister_function_states_for_functions(
                    [(old_func, old_kwargs)], channel_key, tokens=[token]
                )
                continue

            func_scope_id = f"{parent_scope}::{token}"
            state = ObjectStateRegistry.get_by_scope(func_scope_id)
            if state is None:
                continue

            for param_name, new_value in new_kwargs.items():
                old_value = old_kwargs.get(param_name)
                if old_value != new_value and param_name in state.parameters:
                    state.update_parameter(param_name, new_value)
                    logger.debug(
                        f"🔧 Code mode: Updated {func_scope_id}.{param_name}: {old_value} → {new_value}"
                    )

            for param_name in old_kwargs:
                if param_name not in new_kwargs and param_name in state.parameters:
                    state.update_parameter(param_name, None)
                    logger.debug(
                        f"🔧 Code mode: Reset {func_scope_id}.{param_name} to None (removed from kwargs)"
                    )

    def _patch_lazy_constructors(self):
        """Context manager that patches lazy dataclass constructors to preserve None vs concrete distinction."""
        from objectstate import patch_lazy_constructors
        return patch_lazy_constructors()

    def _move_function(self, index, direction):
        """Move function up or down.

        CRITICAL: Does NOT recreate widgets - just reorders existing panes in layout.
        This preserves flash registrations and avoids RuntimeError from deleted widgets.
        """
        if not (0 <= index < len(self.functions)):
            return

        new_index = index + direction
        if not (0 <= new_index < len(self.functions)):
            return

        def mutate() -> None:
            # Swap functions in data
            self.functions[index], self.functions[new_index] = (
                self.functions[new_index],
                self.functions[index],
            )
            self._current_function_tokens[index], self._current_function_tokens[new_index] = (
                self._current_function_tokens[new_index],
                self._current_function_tokens[index],
            )

        def refresh() -> None:
            # Reorder existing panes (NOT recreate) - preserves flash registrations
            self._reorder_function_panes(index, new_index)

        self._commit_pattern_mutation(
            mutation_label="reorder function",
            mutate=mutate,
            refresh_ui=refresh,
        )

    def _reorder_function_panes(self, old_index: int, new_index: int) -> None:
        """Reorder existing panes in layout without recreating them.

        This preserves widget instances and their flash registrations.
        Only the layout order and pane indices are updated.
        """
        if not self.function_panes:
            return

        # Swap panes in our tracking list
        self.function_panes[old_index], self.function_panes[new_index] = \
            self.function_panes[new_index], self.function_panes[old_index]

        # Update indices on the panes
        for i, pane in enumerate(self.function_panes):
            pane.index = i

        from PyQt6 import sip

        # Reorder widgets in layout without recreating them.
        # insertWidget() moves an existing widget if it's already in the layout.
        if any(sip.isdeleted(p) for p in self.function_panes):
            self._populate_function_list()
            return

        for i, pane in enumerate(self.function_panes):
            self.function_layout.insertWidget(i, pane)
    
    def _add_function_at_index(self, index):
        """Add function at specific index (mirrors Textual TUI)."""
        # Show function selector dialog via provider
        selected_function = self.function_selection_provider.select_function(parent=self)

        if selected_function:
            def mutate() -> None:
                new_func_item = (selected_function, {})
                self.functions.insert(index, new_func_item)
                self._current_function_tokens.insert(
                    index, self._get_func_token_generator().ensure()
                )

            self._commit_pattern_mutation(
                mutation_label="add function",
                mutate=mutate,
                refresh_ui=self._populate_function_list,
            )
            logger.debug(f"Added function at index {index}: {selected_function.__name__}")
    
    def _remove_function(self, index: int) -> None:
        """Remove function at index."""
        if not (0 <= index < len(self.functions)):
            return

        func_item = self.functions[index]
        channel_key = self.selected_pattern_key if self.is_dict_mode else None

        def mutate() -> None:
            token = (
                [self._current_function_tokens[index]]
                if index < len(self._current_function_tokens)
                else None
            )
            self._unregister_function_states_for_functions(
                [func_item], channel_key, tokens=token
            )
            self.functions.pop(index)
            if index < len(self._current_function_tokens):
                self._current_function_tokens.pop(index)

        self._commit_pattern_mutation(
            mutation_label="remove function",
            mutate=mutate,
            refresh_ui=self._populate_function_list,
        )
    
    def _on_parameter_changed(self, index, param_name, value):
        """Handle parameter change from function pane."""
        if self._pattern_event_suppression_depth > 0:
            return
        if 0 <= index < len(self.functions):
            def mutate() -> None:
                func, kwargs = self.functions[index]
                # IMPORTANT: Don't mutate kwargs dict in-place.
                # ObjectState uses equality checks; mutating shared dict instances can
                # make changes undetectable and can also leak edits across keys.
                new_kwargs = dict(kwargs)
                new_kwargs[param_name] = value
                self.functions[index] = (func, new_kwargs)

            self._commit_pattern_mutation(
                mutation_label=None,
                mutate=mutate,
                persist_selected_key=False,
            )
    

    

    
    def get_current_functions(self):
        """Get current function list."""
        return self.functions.copy()

    @property
    def current_pattern(self):
        """Get the current pattern data (for parent widgets to access)."""
        self._update_pattern_data()  # Ensure it's up to date

        def _prune_kwargs(func: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
            param_info = SignatureAnalyzer.analyze(func) if func else {}
            pruned = {}
            for key, value in kwargs.items():
                if value is None:
                    continue
                default_info = param_info.get(key)
                if default_info is not None and value == default_info.default_value:
                    continue
                pruned[key] = value
            return pruned

        # Migration fix: Convert any integer keys to string keys for compatibility
        # with pattern detection system which always uses string component values
        if isinstance(self.pattern_data, dict):
            migrated_pattern = {}
            for key, value in self.pattern_data.items():
                str_key = str(key)
                normalized_list = []
                for item in value:
                    func, kwargs = PatternDataManager.extract_func_and_kwargs(item)
                    if func is None:
                        continue
                    pruned_kwargs = _prune_kwargs(func, kwargs)
                    normalized_list.append(func if not pruned_kwargs else (func, pruned_kwargs))
                migrated_pattern[str_key] = normalized_list
            return migrated_pattern

        if isinstance(self.pattern_data, list):
            normalized_list = []
            for item in self.pattern_data:
                func, kwargs = PatternDataManager.extract_func_and_kwargs(item)
                if func is None:
                    continue
                pruned_kwargs = _prune_kwargs(func, kwargs)
                normalized_list.append(func if not pruned_kwargs else (func, pruned_kwargs))

            if len(normalized_list) == 1 and callable(normalized_list[0]):
                return normalized_list[0]

            return normalized_list

        return self.pattern_data
    
    def set_functions(self, functions):
        """Set function list and refresh display."""
        normalized, tokens = self._normalize_function_list(functions or [])
        self.functions = normalized
        self._current_function_tokens = tokens
        self._update_pattern_data()
        self._populate_function_list()

    def set_scope_color_scheme(self, scheme) -> None:
        """Set scope color scheme for styling function panes.

        Called by parent window after scope styling is initialized.
        Stores scheme for newly created panes and applies to existing ones.
        Also applies styling to all child GroupBoxWithHelp and HelpButton widgets.
        """
        logger.info(f"🎨 FunctionListEditorWidget.set_scope_color_scheme called with scheme={scheme}, panes={len(self.function_panes)}")
        self._scope_color_scheme = scheme

        # Apply to all existing panes (title color)
        for pane in self.function_panes:
            pane.set_scope_color_scheme(scheme)

        # Apply scope styling to all child widgets (GroupBoxWithHelp, HelpButton, etc.)
        self._apply_scope_styling_to_children(scheme)

    def set_scope_index(self, scope_index: Optional[int]) -> None:
        """Update scope index used for styling future panes."""
        self.scope_index = scope_index

    def _apply_scope_styling_to_children(self, scheme) -> None:
        """Apply scope styling to all child widgets that need it.

        This mirrors the logic in base_form_dialog._apply_accent_to_help_buttons().
        """
        if not scheme:
            return

        from pyqt_reactive.widgets.shared.clickable_help_components import HelpButton, HelpIndicator, GroupBoxWithHelp
        from pyqt_reactive.widgets.shared.scope_color_utils import tint_color_perceptual

        # Compute accent color from scheme (same logic as ScopedBorderMixin.get_scope_accent_color)
        layers = getattr(scheme, 'step_border_layers', None)
        if layers:
            _, tint_idx, _ = (layers[0] + ("solid",))[:3]
            accent_color = tint_color_perceptual(scheme.base_color_rgb, tint_idx).darker(120)
        else:
            accent_color = tint_color_perceptual(scheme.base_color_rgb, 0).darker(120)

        # Apply to all HelpButtons
        help_btns = self.findChildren(HelpButton)
        logger.info(f"🎨 _apply_scope_styling_to_children: found {len(help_btns)} HelpButtons")
        for help_btn in help_btns:
            help_btn.set_scope_accent_color(accent_color)

        # Apply to all HelpIndicators
        help_indicators = self.findChildren(HelpIndicator)
        logger.info(f"🎨 _apply_scope_styling_to_children: found {len(help_indicators)} HelpIndicators")
        for help_indicator in help_indicators:
            help_indicator.set_scope_accent_color(accent_color)

        # Apply to all GroupBoxWithHelp (scope border pattern)
        # NOTE: Exclude function panes since they're already handled in set_scope_color_scheme()
        groupboxes = self.findChildren(GroupBoxWithHelp)
        non_pane_groupboxes = [gb for gb in groupboxes if gb not in self.function_panes]
        logger.info(f"🎨 _apply_scope_styling_to_children: found {len(groupboxes)} GroupBoxWithHelp, {len(non_pane_groupboxes)} non-pane")
        for groupbox in non_pane_groupboxes:
            groupbox.set_scope_color_scheme(scheme)

    def refresh_from_context(self) -> None:
        """Refresh group_by and variable_components from live ObjectState values."""
        from objectstate import ObjectStateRegistry

        scope = str(self.scope_id or "")
        if not scope:
            return
        state = ObjectStateRegistry.get_by_scope(scope)
        if state is None:
            # ObjectState is authoritative.
            return

        self.current_group_by = state.get_resolved_value("processing_config.group_by")
        self.current_variable_components = (
            state.get_resolved_value("processing_config.variable_components") or []
        )
        self._refresh_component_button()

    def _subscribe_to_context_state_changes(self) -> None:
        """Subscribe to context ObjectState resolved-value changes."""
        if not self.scope_id:
            logger.debug("No scope_id, skipping ObjectState subscription")
            return

        state = ObjectStateRegistry.get_by_scope(self.scope_id)
        if not state:
            logger.warning(f"No ObjectState for scope {self.scope_id}, skipping subscription")
            return

        def on_resolved_changed(changed_paths: set) -> None:
            """Called when context resolved values change."""
            relevant_paths = {"processing_config.group_by", "processing_config.variable_components"}
            if changed_paths & relevant_paths:
                logger.info(f"🔔 FUNC_EDITOR: ObjectState resolved change detected: {changed_paths & relevant_paths}")
                self.refresh_from_context()

        state.on_resolved_changed(on_resolved_changed)
        # Store callback reference for cleanup
        self._resolved_change_callback = on_resolved_changed
        self._subscribed_state = state
        logger.info(f"🔔 FUNC_EDITOR: Subscribed to ObjectState resolved changes for scope {self.scope_id}")

        # Cleanup on widget destruction
        def cleanup_subscription():
            if self._resolved_change_callback is not None and self._subscribed_state is not None:
                self._subscribed_state.off_resolved_changed(self._resolved_change_callback)
                logger.debug(f"🔔 FUNC_EDITOR: Unsubscribed from ObjectState on destruction")
        self.destroyed.connect(cleanup_subscription)

    def set_effective_group_by(self, group_by: Optional[Any]) -> None:
        """Accept authoritative GroupBy from parent (step.processing_config) and refresh UI.

        The parent (window) is responsible for providing the correct GroupBy instance
        from the step.processing_config. This method trusts the type and simply
        updates the widget state and refreshes dependent controls.
        """
        self.current_group_by = group_by
        # Update the button text/state immediately
        self._refresh_component_button()

    def _get_component_button_text(self) -> str:
        """Get text for the component selection button (mirrors Textual TUI)."""
        if self.current_group_by is None or self.current_group_by == self._groupby_enum.NONE:
            return "Component: None"

        # Use the existing _get_enum_display_text function for consistent enum display handling
        component_type = _get_enum_display_text(self.current_group_by).title()

        if self.is_dict_mode and isinstance(self.pattern_data, dict):
            keys = sorted(self.pattern_data.keys())
            if not keys:
                return f"{component_type}: None"

            key = self.selected_pattern_key
            if key is None or key not in self.pattern_data:
                key = keys[0]

            display_name = self._get_component_display_name(str(key))
            return f"{component_type}: {display_name}"

        return f"{component_type}: None"

    def _get_component_display_name(self, component_key: str) -> str:
        """Get display name for component key, using metadata if available (mirrors Textual TUI)."""
        if self.current_group_by:
            metadata_name = self.component_selection_provider.get_component_display_name(
                self.current_group_by, component_key
            )
            if metadata_name:
                # Keep the key visible even when metadata exists.
                # This helps disambiguate and matches common microscope workflows where
                # users think in channel indices but still want the stain/name.
                return f"{component_key} : {metadata_name}"
        return component_key

    def _is_component_button_disabled(self) -> bool:
        """Check if component selection button should be disabled (mirrors Textual TUI)."""
        return (
            self.current_group_by is None or
            self.current_group_by == self._groupby_enum.NONE or
            (self.current_variable_components and
             self.current_group_by.value in [vc.value for vc in self.current_variable_components])
        )

    def show_component_selection_dialog(self):
        """Show the component selection dialog (mirrors Textual TUI)."""
        # Check if component selection is disabled
        if self._is_component_button_disabled():
            logger.debug("Component selection is disabled")
            return

        available_components = self.component_selection_provider.get_component_keys(
            self.current_group_by
        )
        if not available_components:
            return

        # Get current selection from pattern data (mirrors Textual TUI logic)
        selected_components = self._get_current_component_selection()

        # Show provider selection UI
        result = self.component_selection_provider.select_components(
            available_components=available_components,
            selected_components=selected_components,
            group_by=self.current_group_by,
            parent=self,
        )

        if result is not None:
            self._handle_component_selection(result)

    def _get_current_component_selection(self):
        """Get current component selection from pattern data (mirrors Textual TUI logic)."""
        # If in dict mode, return the keys of the dict as the current selection (sorted)
        if self.is_dict_mode and isinstance(self.pattern_data, dict):
            return sorted(list(self.pattern_data.keys()))

        # If not in dict mode, check the cache (sorted)
        cached_selection = self.component_selections.get(self.current_group_by, [])
        return sorted(cached_selection)

    def _handle_component_selection(self, new_components):
        """Handle component selection result (mirrors Textual TUI)."""
        # Save selection to cache for current group_by
        if self.current_group_by is not None and self.current_group_by != self._groupby_enum.NONE:
            self.component_selections[self.current_group_by] = new_components
            logger.debug(
                "Context '%s': Cached selection for %s: %s",
                self.context_identifier,
                self.current_group_by.value,
                new_components,
            )

        # ATOMIC: coalesce component selection change into a single undo step
        with ObjectStateRegistry.atomic("edit components"):
            # Update pattern structure based on component selection (mirrors Textual TUI)
            self._update_components(new_components)

            # Update component button text and navigation
            self._refresh_component_button()
            logger.debug(f"Updated components: {new_components}")

            self._emit_pattern_changed()

    def _update_components(self, new_components):
        """Update function pattern structure based on component selection (mirrors Textual TUI)."""
        # Sort new components for consistent ordering
        if new_components:
            new_components = sorted(new_components)

        if not new_components:
            # No components selected - revert to list mode
            if self.is_dict_mode:
                # We're discarding dict-mode keys. Unregister function ObjectStates
                # for all keys so we don't leak stale states.
                old_pattern = (
                    self.pattern_data if isinstance(self.pattern_data, dict) else {}
                )
                old_tokens = (
                    self._pattern_tokens if isinstance(self._pattern_tokens, dict) else {}
                )
                for old_key, old_functions in old_pattern.items():
                    # Keep the currently selected channel's function states.
                    # Those functions become the new list-mode pattern.
                    if self.selected_pattern_key and old_key == self.selected_pattern_key:
                        continue
                    self._unregister_function_states_for_functions(
                        old_functions,
                        str(old_key),
                        tokens=list(old_tokens.get(str(old_key), [])),
                    )

                # Save current functions to list mode
                self.pattern_data = self.functions
                selected_key = str(self.selected_pattern_key) if self.selected_pattern_key is not None else ""
                self._pattern_tokens = (
                    list(old_tokens.get(selected_key, []))
                    if isinstance(old_tokens, dict)
                    else list(self._current_function_tokens)
                )
                self._current_function_tokens = list(self._pattern_tokens)
                self.is_dict_mode = False
                self.selected_pattern_key = None
                logger.debug("Reverted to list mode (no components selected)")
            self._populate_function_list()
            self._update_navigation_buttons()
            self._persist_pattern_tokens_to_state()
            return
        else:
            # Use component strings directly - no conversion needed
            component_keys = new_components

            # Components selected - ensure dict mode
            if not self.is_dict_mode:
                # Convert to dict mode
                current_functions = self.functions
                self.pattern_data = {component_keys[0]: current_functions}
                list_tokens = (
                    list(self._pattern_tokens)
                    if isinstance(self._pattern_tokens, list)
                    else list(self._current_function_tokens)
                )
                self._pattern_tokens = {component_keys[0]: list_tokens}
                self.is_dict_mode = True
                self.selected_pattern_key = component_keys[0]
                self._current_function_tokens = list_tokens
                self._record_selected_pattern_key()

                # Add other components with copy of current functions
                for component_key in component_keys[1:]:
                    self.pattern_data[component_key] = list(current_functions)
                    self._pattern_tokens[component_key] = list(list_tokens)  # type: ignore[index]
            else:
                # Already in dict mode - update components
                old_pattern = self.pattern_data.copy() if isinstance(self.pattern_data, dict) else {}
                old_tokens = (
                    self._pattern_tokens.copy()
                    if isinstance(self._pattern_tokens, dict)
                    else {}
                )

                # Create a persistent storage for deselected components (mirrors Textual TUI)
                self._deselected_components_storage = {}

                # Save currently deselected components to storage
                for old_key, old_functions in old_pattern.items():
                    if old_key not in component_keys:
                        self._deselected_components_storage[old_key] = old_functions
                        # Unregister function ObjectStates for removed keys.
                        self._unregister_function_states_for_functions(
                            old_functions,
                            str(old_key),
                            tokens=list(old_tokens.get(str(old_key), [])),
                        )
                        logger.debug(f"Saved {len(old_functions)} functions for deselected component {old_key}")

                new_pattern = {}
                new_tokens: Dict[str, List[str]] = {}

                # Restore functions for components (from current pattern or storage)
                # Get a reference pattern to copy from (first existing component)
                reference_functions = None
                reference_tokens = None
                for ref_key in component_keys:
                    if ref_key in old_pattern and old_pattern[ref_key]:
                        reference_functions = old_pattern[ref_key]
                        reference_tokens = old_tokens.get(str(ref_key), [])
                        break

                for component_key in component_keys:
                    if component_key in old_pattern:
                        # Component was already selected - keep its functions
                        new_pattern[component_key] = old_pattern[component_key]
                        new_tokens[component_key] = list(
                            old_tokens.get(str(component_key), [])
                        )
                    elif component_key in self._deselected_components_storage:
                        # Component was previously deselected - restore its functions
                        new_pattern[component_key] = self._deselected_components_storage[component_key]
                        new_tokens[component_key] = list(
                            old_tokens.get(str(component_key), [])
                        )
                        logger.debug(f"Restored {len(new_pattern[component_key])} functions for reselected component {component_key}")
                    else:
                        # New component - copy from reference pattern if available
                        if reference_functions is not None:
                            new_pattern[component_key] = list(reference_functions)
                            new_tokens[component_key] = list(reference_tokens) if reference_tokens else []
                            logger.debug(f"Copied {len(reference_functions)} functions to new component {component_key}")
                        else:
                            # No reference available - start with empty functions
                            new_pattern[component_key] = []
                            new_tokens[component_key] = []

                self.pattern_data = new_pattern
                self._pattern_tokens = new_tokens

        # Update selected channel if current one is no longer available
        if self.selected_pattern_key not in component_keys:
            self.selected_pattern_key = component_keys[0]
            self.functions = new_pattern[self.selected_pattern_key]
        if isinstance(self._pattern_tokens, dict) and self.selected_pattern_key is not None:
            self._current_function_tokens = list(
                self._pattern_tokens.get(str(self.selected_pattern_key), [])
            )

        # Update UI to reflect changes
        self._populate_function_list()
        self._update_navigation_buttons()
        self._persist_pattern_tokens_to_state()

    def _refresh_component_button(self):
        """Refresh the component button text and state (mirrors Textual TUI)."""
        # The component button is always created (even when render_header=False),
        # because DualEditorWindow extracts the action buttons container and
        # renders it in its own header.
        new_text = self._get_component_button_text()
        old_text = self.component_btn.text()
        logger.info(
            f"🔄 _refresh_component_button: old={old_text!r}, new={new_text!r}, group_by={self.current_group_by}"
        )
        self.component_btn.setText(new_text)
        self.component_btn.setEnabled(not self._is_component_button_disabled())

        # Navigation buttons only exist when the header is rendered.
        if self._render_header:
            self._update_navigation_buttons()



    def _update_navigation_buttons(self):
        """Update visibility of channel navigation buttons (mirrors Textual TUI)."""
        # Show navigation buttons only in dict mode with multiple keys.
        # Buttons exist regardless of render_header; DualEditorWindow embeds
        # the action button container when render_header=False.
        show_nav = (
            self.is_dict_mode
            and isinstance(self.pattern_data, dict)
            and len(self.pattern_data) > 1
        )

        self.prev_key_btn.setVisible(show_nav)
        self.next_key_btn.setVisible(show_nav)
    
    def get_action_buttons(self) -> Optional[QWidget]:
        """Get the action buttons container for external placement.
        
        This method allows parent windows (e.g., DualEditorWindow) to
        extract and reposition action buttons without modifying this widget's
        internal structure.
        
        Returns:
            QWidget: Container widget with action buttons (Add, Code, Component).
                      Returns None if header is rendered (buttons are in use).
        """
        if self._render_header:
            return None
        return self._action_buttons_container


    def _navigate_pattern_key(self, direction: int):
        """Navigate to next/previous pattern key (with looping)."""
        if not self.is_dict_mode or not isinstance(self.pattern_data, dict):
            return
        
        keys = sorted(self.pattern_data.keys())
        if len(keys) <= 1:
            return
        
        try:
            current_index = keys.index(self.selected_pattern_key)
            new_index = (current_index + direction) % len(keys)
            new_key = keys[new_index]

            self._select_pattern_key(
                new_key,
                commit_current_view=True,
                persist_selection=True,
            )
            logger.debug(f"Navigated to key {new_key}")
        except (ValueError, IndexError):
            raise

    def select_pattern_key(self, key: str) -> None:
        """Select dict-pattern key for viewing/editing."""
        if not self.is_dict_mode or not isinstance(self.pattern_data, dict):
            self._pending_selected_pattern_key = key
            return
        if key not in self.pattern_data:
            return

        self._pending_selected_pattern_key = None
        self._select_pattern_key(
            key,
            commit_current_view=True,
            persist_selection=True,
        )

    def select_pattern_key_for_function_token(self, token: str) -> None:
        """Select dict-pattern key that contains a function entry token.

        Used by OpenHCS time-travel navigation to restore the UI view to the
        correct channel when a function inside a dict pattern changed.
        """
        if not token or not self.is_dict_mode or not isinstance(self.pattern_data, dict):
            return
        if not isinstance(self._pattern_tokens, dict):
            return

        target_channel = None
        for channel_key, channel_tokens in self._pattern_tokens.items():
            if str(token) in {str(t) for t in channel_tokens}:
                target_channel = str(channel_key)
                break

        if target_channel is None:
            return

        if self.selected_pattern_key != target_channel:
            self._select_pattern_key(
                target_channel,
                commit_current_view=True,
                persist_selection=True,
            )

    def _update_pattern_data(self):
        """Update pattern_data based on current functions and mode (mirrors Textual TUI)."""
        # CRITICAL: Sync all function panes to get reconstructed kwargs from ObjectState
        # before reading self.functions. Otherwise we get stale flattened kwargs!
        for pane in self.function_panes:
            if pane and hasattr(pane, 'sync_kwargs'):
                pane.sync_kwargs()

        sanitized_functions = []
        for item in self.functions:
            func, kwargs = PatternDataManager.extract_func_and_kwargs(item)
            if func is None:
                continue
            clean_kwargs = self._sanitize_pattern_kwargs(
                kwargs if isinstance(kwargs, dict) else {}
            )
            sanitized_functions.append((func, clean_kwargs))
        self.functions = sanitized_functions
        if len(self._current_function_tokens) < len(self.functions):
            missing = len(self.functions) - len(self._current_function_tokens)
            self._current_function_tokens.extend(
                self._get_func_token_generator().ensure() for _ in range(missing)
            )
        elif len(self._current_function_tokens) > len(self.functions):
            self._current_function_tokens = self._current_function_tokens[
                : len(self.functions)
            ]

        if self.is_dict_mode and self.selected_pattern_key is not None:
            # Save current functions to the selected channel
            # CRITICAL: Create a NEW dict so ObjectState equality check detects changes
            # If we modify the same dict object, current_value == value is always True
            old_pattern = self.pattern_data if isinstance(self.pattern_data, dict) else {}
            new_pattern = dict(old_pattern)  # Shallow copy of dict
            new_pattern[self.selected_pattern_key] = self.functions.copy()
            self.pattern_data = new_pattern
            self._set_tokens_for_current_view(self._current_function_tokens)
            logger.debug(f"Saving {len(self.functions)} functions to key {self.selected_pattern_key}")
        else:
            # List mode - pattern_data is a COPY of functions list
            # CRITICAL: Must be a copy so ObjectState equality check detects changes
            self.pattern_data = self.functions.copy()
            self._set_tokens_for_current_view(self._current_function_tokens)
        self._persist_pattern_tokens_to_state()
