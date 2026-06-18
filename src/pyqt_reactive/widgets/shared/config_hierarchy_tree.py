"""
Shared helpers for rendering configuration hierarchy trees in the PyQt6 GUI.

Both the pipeline ConfigWindow and the StepParameterEditor need to display the
same inheritance-aware tree that highlights which dataclass sections are
editable and which are inherited. This module centralizes the logic so the UI
widgets only need to provide their dataclass inputs and navigation callbacks.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from types import UnionType
from typing import Callable, ClassVar, Dict, Type, Optional, Iterable, Mapping, Union, get_args, get_origin

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QPainter, QFont, QFontMetrics, QBrush
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QStyledItemDelegate, QStyleOptionViewItem, QStyle

from metaclass_registry import AutoRegisterMeta
from objectstate.lazy_factory import get_base_type_for_lazy, is_lazy_dataclass
from objectstate import is_ui_hidden_config_type
from pyqt_reactive.widgets.shared.config_tree_contracts import (
    ConfigTreeFlashManager,
    ScopeColorSchemeHost,
    TreeFlashColorProvider,
)
from pyqt_reactive.widgets.shared.scope_visual_config import ScopeColorScheme

logger = logging.getLogger(__name__)

# Custom data role for flash key (matches list_item_delegate pattern)
TREE_FLASH_KEY_ROLE = Qt.ItemDataRole.UserRole + 20
TreeItemDoubleClickHandler = Callable[[QTreeWidgetItem, int], None]
ScrollToSection = Callable[[str], None]
FieldForClass = Callable[[Type], str | None]


class ConfigTreeItemKind(str, Enum):
    """Closed item kinds stored in config hierarchy tree payloads."""

    DATACLASS = "dataclass"
    INHERITANCE_LINK = "inheritance_link"


@dataclass(frozen=True, slots=True)
class ConfigTreeItemPayload:
    """Nominal payload stored on config hierarchy tree items."""

    item_type: ConfigTreeItemKind
    class_obj: Type | None = None
    field_name: str | None = None
    field_path: str | None = None
    target_class: Type | None = None
    ui_hidden: bool = False

    @property
    def navigation_path(self) -> str | None:
        return self.field_path or self.field_name

    def alternate_class_field_name(self, formatter) -> str | None:
        if self.class_obj is None:
            return None
        return formatter(self.class_obj.__name__)


@dataclass(frozen=True, slots=True)
class ConfigTreeNavigation:
    """Navigation operations needed by config tree item activators."""

    scroll_to_section: ScrollToSection
    field_for_class: FieldForClass


class ConfigTreeItemActivator(ABC, metaclass=AutoRegisterMeta):
    """Behavior for one closed config tree item kind."""

    __registry_key__ = "item_kind"
    __skip_if_no_key__ = True

    item_kind: ClassVar[ConfigTreeItemKind]

    @classmethod
    def for_item_kind(cls, item_kind: ConfigTreeItemKind) -> "ConfigTreeItemActivator":
        """Return the registered activator for a tree item kind."""
        return cls.__registry__[item_kind]()

    @abstractmethod
    def activate(
        self,
        payload: ConfigTreeItemPayload,
        navigation: ConfigTreeNavigation,
    ) -> None:
        """Activate one tree item payload."""
        ...


class DataclassTreeItemActivator(ConfigTreeItemActivator):
    """Navigate to the dataclass section represented by a tree item."""

    item_kind = ConfigTreeItemKind.DATACLASS

    def activate(
        self,
        payload: ConfigTreeItemPayload,
        navigation: ConfigTreeNavigation,
    ) -> None:
        if payload.ui_hidden or payload.navigation_path is None:
            return
        navigation.scroll_to_section(payload.navigation_path)


class InheritanceLinkTreeItemActivator(ConfigTreeItemActivator):
    """Navigate to the editable field represented by an inheritance link."""

    item_kind = ConfigTreeItemKind.INHERITANCE_LINK

    def activate(
        self,
        payload: ConfigTreeItemPayload,
        navigation: ConfigTreeNavigation,
    ) -> None:
        if payload.ui_hidden or payload.target_class is None:
            return
        field_name = navigation.field_for_class(payload.target_class)
        if field_name is None:
            logger.warning(
                "Could not find field for inherited class %s",
                payload.target_class.__name__,
            )
            return
        navigation.scroll_to_section(field_name)


def activate_config_tree_item(
    payload: ConfigTreeItemPayload,
    *,
    scroll_to_section: ScrollToSection,
    field_for_class: FieldForClass,
) -> None:
    """Apply the standard navigation behavior for a config tree payload."""
    navigation = ConfigTreeNavigation(
        scroll_to_section=scroll_to_section,
        field_for_class=field_for_class,
    )
    ConfigTreeItemActivator.for_item_kind(payload.item_type).activate(
        payload,
        navigation,
    )

class TreeItemFlashDelegate(QStyledItemDelegate):
    """Custom delegate for tree items with flash behind text.

    TRUE O(1) ARCHITECTURE: Flash lookup uses pre-computed colors from GlobalFlashCoordinator.
    This delegate draws flash BEHIND text (like MultilinePreviewItemDelegate for list items)
    so text remains readable during flash animations.
    """

    def __init__(self, parent=None, manager: Optional[TreeFlashColorProvider] = None):
        """Initialize delegate.

        Args:
            parent: Parent widget (QTreeWidget)
            manager: Flash manager with get_flash_color_for_key() method
        """
        super().__init__(parent)
        self._manager = manager

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        """Paint tree item with flash BEHIND text."""
        # Prepare a copy to let style draw backgrounds, hover, selection, etc.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        # Capture text and prevent default text draw
        text = opt.text or ""
        opt.text = ""

        # Draw flash background BEHIND text (inside item rect)
        flash_key = index.data(TREE_FLASH_KEY_ROLE)
        if flash_key and self._manager is not None:
            flash_color = self._manager.get_flash_color_for_key(flash_key)
            if flash_color and flash_color.alpha() > 0:
                # Override flash color to match the owning window's scope color scheme.
                window = self.parent()
                while window is not None:
                    if isinstance(window, ScopeColorSchemeHost) and window._scope_color_scheme is not None:
                        scheme_color = self._scheme_flash_color(window._scope_color_scheme)
                        if scheme_color is not None:
                            # Keep animation alpha from coordinator.
                            flash_color = QColor(
                                scheme_color.red(),
                                scheme_color.green(),
                                scheme_color.blue(),
                                flash_color.alpha(),
                            )
                        break
                    window = window.parent()
                painter.fillRect(option.rect, flash_color)

        # Let the style draw selection, hover, backgrounds (except text)
        self.parent().style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, self.parent())

        # Now draw text manually ON TOP of flash
        painter.save()

        # Determine text color based on selection state
        is_selected = option.state & QStyle.StateFlag.State_Selected

        # Get font from option
        font = QFont(option.font)

        # Check if item is italic (ui_hidden items use italic)
        item_font = index.data(Qt.ItemDataRole.FontRole)
        if item_font:
            font = QFont(item_font)

        painter.setFont(font)
        fm = QFontMetrics(font)

        # Calculate text position
        # Qt's option.rect is already indented for depth, just add small padding for branch indicator
        text_rect = option.rect
        x_offset = text_rect.left() + 2  # 2px padding after branch indicator
        y_offset = text_rect.top() + fm.ascent() + (text_rect.height() - fm.height()) // 2

        # Determine text color
        if is_selected:
            color = option.palette.highlightedText().color()
        else:
            # Check for custom foreground (ui_hidden items use gray)
            fg = index.data(Qt.ItemDataRole.ForegroundRole)
            if fg:
                if isinstance(fg, QColor):
                    color = fg
                elif isinstance(fg, QBrush):
                    color = fg.color()
                else:
                    color = QColor(fg)
            else:
                color = option.palette.text().color()

        painter.setPen(color)
        painter.drawText(x_offset, y_offset, text)

        painter.restore()

    @staticmethod
    def _scheme_flash_color(scheme: ScopeColorScheme) -> Optional[QColor]:
        """Return the scheme-tinted flash color for tree rows."""
        if not scheme.base_color_rgb or not scheme.step_border_layers:
            return None

        from pyqt_reactive.widgets.shared.scope_color_utils import tint_color_perceptual

        _, tint_idx, _ = (scheme.step_border_layers[0] + ("solid",))[:3]
        return tint_color_perceptual(scheme.base_color_rgb, tint_idx).darker(120)


class ConfigHierarchyTreeHelper:
    """Utility for building configuration hierarchy trees.

    TRUE O(1) FLASH ARCHITECTURE: Tree items are registered with WindowFlashOverlay
    during population. Flash rendering happens in the window overlay's single paintEvent.

    UNIFIED DIRTY TRACKING: Automatically subscribes to ObjectState.on_state_changed()
    when state is provided, and updates tree item styling reactively.
    """

    _INHERITANCE_TOOLTIP = "This configuration is not editable in the UI (inherited by other configs)"

    def __init__(self):
        self._flash_manager = None
        self._current_tree: Optional[QTreeWidget] = None
        # Mapping from dotted path to QTreeWidgetItem for dirty styling updates
        self._path_to_item: Dict[str, QTreeWidgetItem] = {}
        self._dirty_callback = None
        self._tree_for_dirty: Optional[QTreeWidget] = None
        self._strip_config_suffix = False
        # Dirty tracking subscription
        self._state: Optional['ObjectState'] = None

    def create_tree_widget(
        self,
        *,
        header_label: str = "Configuration Hierarchy",
        minimum_width: int = 0,  # Allow collapsing to 0 for splitter
        flash_manager: Optional[ConfigTreeFlashManager] = None,
        state: Optional['ObjectState'] = None,
        strip_config_suffix: bool = False,
    ) -> QTreeWidget:
        """Create a pre-configured QTreeWidget for hierarchy display.

        Args:
            header_label: Header text for the tree
            minimum_width: Minimum width (0 allows free splitter movement)
            flash_manager: Manager with register_flash_tree_item() for O(1) flash
            state: ObjectState for automatic dirty tracking subscription
        """
        tree = QTreeWidget()
        tree.setHeaderLabel(header_label)
        tree.setMinimumWidth(minimum_width)  # 0 allows free movement in splitter
        tree.setExpandsOnDoubleClick(False)

        if flash_manager is not None and not isinstance(flash_manager, ConfigTreeFlashManager):
            raise TypeError(
                "Config hierarchy tree flash support requires ConfigTreeFlashManager "
                f"but received {type(flash_manager).__name__}."
            )

        # Store flash manager for use during population
        self._flash_manager = flash_manager
        self._current_tree = tree
        self._strip_config_suffix = strip_config_suffix
        # Fresh mapping per tree build to avoid stale item references
        self._path_to_item = {}
        # Track dirty callbacks per tree to allow rebuilding subscriptions on re-init
        self._tree_for_dirty = tree

        # Install delegate that draws flash BEHIND text
        if flash_manager is not None:
            delegate = TreeItemFlashDelegate(parent=tree, manager=flash_manager)
            tree.setItemDelegate(delegate)

        # Subscribe to dirty state changes for reactive tree styling
        if state is not None:
            self._state = state
            self._subscribe_to_dirty_changes(tree)

        # ASYNC FIX: Re-run dirty styling when async form build completes
        # During async build, nested_managers are populated incrementally, so
        # groupbox dirty markers need to be updated again after all are ready
        if flash_manager is not None:
            flash_manager._on_build_complete_callbacks.append(
                lambda: self.initialize_dirty_styling()
            )

        return tree

    def create_tree_from_root_dataclass(
        self,
        *,
        root_dataclass: Type,
        form_manager: ConfigTreeFlashManager,
        state: Optional['ObjectState'] = None,
        strip_config_suffix: bool = True,
        on_item_double_clicked: TreeItemDoubleClickHandler,
    ) -> QTreeWidget:
        """Create and populate a hierarchy tree from a root dataclass."""
        tree = self.create_tree_widget(
            flash_manager=form_manager,
            state=state,
            strip_config_suffix=strip_config_suffix,
        )
        self.populate_from_root_dataclass(tree, root_dataclass)
        self._complete_populated_tree(
            tree=tree,
            form_manager=form_manager,
            on_item_double_clicked=on_item_double_clicked,
        )
        return tree

    def create_tree_from_mapping(
        self,
        *,
        dataclass_params: Dict[str, Type],
        form_manager: ConfigTreeFlashManager,
        state: Optional['ObjectState'] = None,
        strip_config_suffix: bool = True,
        on_item_double_clicked: TreeItemDoubleClickHandler,
    ) -> QTreeWidget:
        """Create and populate a hierarchy tree from parameter-name mappings."""
        tree = self.create_tree_widget(
            flash_manager=form_manager,
            state=state,
            strip_config_suffix=strip_config_suffix,
        )
        self.populate_from_mapping(tree, dataclass_params)
        self._complete_populated_tree(
            tree=tree,
            form_manager=form_manager,
            on_item_double_clicked=on_item_double_clicked,
        )
        return tree

    def _complete_populated_tree(
        self,
        *,
        tree: QTreeWidget,
        form_manager: ConfigTreeFlashManager,
        on_item_double_clicked: TreeItemDoubleClickHandler,
    ) -> None:
        """Finish tree wiring after a caller-specific population strategy."""
        self.initialize_dirty_styling()
        form_manager.register_repaint_callback(lambda: tree.viewport().update())
        tree.itemDoubleClicked.connect(on_item_double_clicked)

    def _subscribe_to_dirty_changes(self, tree: QTreeWidget) -> None:
        """Subscribe to ObjectState dirty changes for reactive styling.

        NOTE: This only sets up the subscription. Call initialize_dirty_styling()
        AFTER populating the tree to apply initial dirty state.
        """
        if self._state is None:
            return

        def on_state_changed():
            dirty_fields = self._state.dirty_fields
            self.update_dirty_styling(dirty_fields)
            tree.viewport().update()

        self._state.on_state_changed(on_state_changed)
        self._dirty_callback = on_state_changed
        self._tree_for_dirty = tree  # Store for initialize_dirty_styling

    def initialize_dirty_styling(self) -> None:
        """Apply initial dirty styling based on current state.

        Call this AFTER populating the tree (after _path_to_item is filled).
        """
        if self._state is None:
            return
        dirty_fields = self._state.dirty_fields
        self.update_dirty_styling(dirty_fields)
        if self._tree_for_dirty:
            self._tree_for_dirty.viewport().update()

    def cleanup_subscriptions(self) -> None:
        """Unsubscribe from ObjectState dirty changes. Call on window close."""
        if self._state is not None:
            if self._dirty_callback is not None:
                self._state.off_state_changed(self._dirty_callback)
                self._dirty_callback = None
            self._state = None

    def apply_scope_background(self, tree: QTreeWidget, scheme: ScopeColorScheme) -> None:
        """Apply scope-colored background tint to tree widget.

        Args:
            tree: The QTreeWidget to style
            scheme: ScopeColorScheme with base_color_rgb and step_border_layers
        """
        from pyqt_reactive.widgets.shared.scope_color_utils import tint_color_perceptual
        from pyqt_reactive.widgets.shared.scope_visual_config import ScopeVisualConfig

        base_rgb = scheme.base_color_rgb
        if not base_rgb:
            return

        layers = scheme.step_border_layers
        if layers:
            _, tint_idx, _ = (layers[0] + ("solid",))[:3]
        else:
            tint_idx = 1

        color = tint_color_perceptual(base_rgb, tint_idx)
        opacity = ScopeVisualConfig.TREE_BG_OPACITY

        # Apply via stylesheet (most robust for QTreeWidget)
        r, g, b = color.red(), color.green(), color.blue()
        alpha = int(255 * opacity)
        tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: rgba({r}, {g}, {b}, {alpha});
            }}
            QTreeWidget::item {{
                background-color: transparent;
            }}
        """)

    def update_dirty_styling(self, dirty_fields: set) -> None:
        """Update tree item AND groupbox styling based on dirty and signature diff fields.

        Two orthogonal visual semantics:
        - Asterisk (*): dirty (resolved_live != resolved_saved)
        - Underline: signature diff (raw != signature default)

        Single source of truth: prefixes computed ONCE and used for both
        tree items and groupbox titles (via flash_manager).
        """
        # Precompute dirty prefixes (for asterisk)
        dirty_prefixes = self._compute_prefixes(dirty_fields)

        # Precompute signature diff prefixes (for underline)
        sig_diff_fields = self._state.signature_diff_fields if self._state else set()
        sig_diff_prefixes = self._compute_prefixes(sig_diff_fields)

        # Update tree items
        seen_items = set()
        for path, item in self._path_to_item.items():
            if id(item) in seen_items:
                continue
            seen_items.add(id(item))

            payload = self._required_item_payload(item)
            field_name = payload.field_name
            alt_name = payload.alternate_class_field_name(self._to_snake_case)

            is_dirty = self._matches_prefix(path, field_name, alt_name, dirty_prefixes)
            has_sig_diff = self._matches_prefix(path, field_name, alt_name, sig_diff_prefixes)

            # Asterisk for dirty
            current_text = item.text(0)
            has_marker = current_text.startswith("* ")
            if is_dirty and not has_marker:
                item.setText(0, f"* {current_text}")
            elif not is_dirty and has_marker:
                item.setText(0, current_text[2:])  # Remove "* " prefix

            # Underline for signature diff
            font = item.font(0)
            font.setUnderline(has_sig_diff)
            item.setFont(0, font)

        # Update groupbox titles using same prefixes (single source of truth)
        if self._flash_manager is not None:
            self._flash_manager.update_groupbox_dirty_markers(dirty_prefixes, sig_diff_prefixes)

    def _required_item_payload(
        self,
        item: QTreeWidgetItem,
    ) -> ConfigTreeItemPayload:
        payload = self._item_payload(item)
        if payload is None:
            raise TypeError(
                "Config hierarchy tree item data must be ConfigTreeItemPayload; got None."
            )
        return payload

    def _compute_prefixes(self, fields: set) -> set:
        """Compute field paths and all their ancestor prefixes."""
        prefixes = set()
        for field_path in fields:
            parts = field_path.split('.')
            for i in range(1, len(parts) + 1):
                prefixes.add('.'.join(parts[:i]))
        return prefixes

    def _matches_prefix(self, path: str, field_name: str, alt_name: str, prefixes: set) -> bool:
        """Check if any identifier matches the prefix set."""
        return (
            path in prefixes
            or (field_name and field_name in prefixes)
            or (alt_name and alt_name in prefixes)
        )

    def _register_flash_element(self, item: QTreeWidgetItem, field_path: str) -> None:
        """Register tree item for flash rendering.

        Stores SCOPED flash key in item data for delegate lookup, and registers with
        WindowFlashOverlay (with skip_overlay_paint=True since delegate handles painting).

        Tree items use 'tree::' prefix to avoid key collision with groupboxes,
        allowing independent flash control (tree can flash without groupbox and vice versa).
        """
        if self._flash_manager is None or self._current_tree is None:
            return

        # Tree items use separate key namespace to avoid groupbox collision
        tree_key = f"tree::{field_path}"

        # Get scoped key from flash manager (matches what's used for color lookup)
        scoped_key = self._flash_manager._get_scoped_flash_key(tree_key)

        # Store SCOPED flash key in item data for delegate to look up
        item.setData(0, TREE_FLASH_KEY_ROLE, scoped_key)

        tree = self._current_tree
        # Create closure that finds item's current index (handles tree rebuild)
        def get_index():
            return tree.indexFromItem(item)

        self._flash_manager.register_flash_tree_item(tree_key, tree, get_index)

    def populate_from_root_dataclass(
        self,
        tree: QTreeWidget,
        root_dataclass: Type,
        *,
        skip_root_ui_hidden: bool = True,
    ) -> None:
        """Populate the tree using the children of a root dataclass."""
        if not is_dataclass(root_dataclass):
            return

        self._current_tree = tree
        self._add_ui_visible_dataclasses_to_tree(
            parent_item=tree,
            obj_type=root_dataclass,
            is_root=True,
            skip_root_ui_hidden=skip_root_ui_hidden,
        )

    def populate_from_mapping(
        self,
        tree: QTreeWidget,
        dataclass_mapping: Dict[str, Type],
    ) -> None:
        """Populate the tree given a dict of field_name -> dataclass type."""
        self._current_tree = tree
        for field_name, obj_type in dataclass_mapping.items():
            base_type = self.get_base_type(obj_type)
            label = self._format_label(base_type.__name__)
            path = field_name
            alt_path = self._to_snake_case(base_type.__name__)

            item = QTreeWidgetItem([label])
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                ConfigTreeItemPayload(
                    item_type=ConfigTreeItemKind.DATACLASS,
                    class_obj=obj_type,
                    field_name=field_name,
                    field_path=path,
                    ui_hidden=False,
                ),
            )
            tree.addTopLevelItem(item)
            # Store mapping for dirty styling updates (support both field and snake_case type name)
            self._store_item_paths(item, [path, alt_path])
            # TRUE O(1): Register with WindowFlashOverlay
            self._register_flash_element(item, path)
            self.add_inheritance_info(item, base_type)

    # ------------------------------------------------------------------
    # Internal helpers shared by both population strategies
    # ------------------------------------------------------------------

    def _add_ui_visible_dataclasses_to_tree(
        self,
        parent_item,
        obj_type: Type,
        *,
        is_root: bool = False,
        skip_root_ui_hidden: bool = True,
        parent_path: str = "",
    ) -> None:
        """Recursively add dataclass children that are shown in the UI."""
        for field in fields(obj_type):
            field_type = field.type
            if not is_dataclass(field_type):
                continue

            base_type = self.get_base_type(field_type)
            display_name = self._format_label(base_type.__name__)
            ui_hidden = self.is_field_ui_hidden(obj_type, field.name, field_type)

            if is_root and skip_root_ui_hidden and ui_hidden:
                continue

            label = display_name if is_root else f"{field.name} ({display_name})"
            path = field.name if not parent_path else f"{parent_path}.{field.name}"
            alt_name = self._to_snake_case(base_type.__name__)
            alt_path = alt_name if not parent_path else f"{parent_path}.{alt_name}"

            item = QTreeWidgetItem([label])
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                ConfigTreeItemPayload(
                    item_type=ConfigTreeItemKind.DATACLASS,
                    class_obj=field_type,
                    field_name=field.name,
                    field_path=path,
                    ui_hidden=ui_hidden,
                ),
            )

            if ui_hidden:
                font = item.font(0)
                font.setItalic(True)
                item.setFont(0, font)
                item.setForeground(0, QColor(128, 128, 128))
                item.setToolTip(0, self._INHERITANCE_TOOLTIP)

            if isinstance(parent_item, QTreeWidget):
                parent_item.addTopLevelItem(item)
            else:
                parent_item.addChild(item)

            # Store mapping for dirty styling updates
            self._store_item_paths(item, [path, alt_path])

            # TRUE O(1): Register with WindowFlashOverlay
            self._register_flash_element(item, path)

            self.add_inheritance_info(item, base_type)
            self._add_ui_visible_dataclasses_to_tree(
                parent_item=item,
                obj_type=base_type,
                is_root=False,
                skip_root_ui_hidden=False,
                parent_path=path,
            )

    def _store_item_paths(self, item: QTreeWidgetItem, paths: Iterable[str]) -> None:
        """Store one or more paths for a tree item, skipping empties and duplicates."""
        for path in paths:
            if not path:
                continue
            if path not in self._path_to_item:
                self._path_to_item[path] = item

    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Convert CamelCase/PascalCase to snake_case for matching dirty paths."""
        import re
        if not name:
            return ""
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

    def _format_label(self, label: str) -> str:
        """Optionally strip 'Config' suffix from labels for presentation only."""
        if self._strip_config_suffix and label.endswith("Config"):
            return label[:-6]
        return label

    def is_field_ui_hidden(
        self,
        obj_type: Type,
        field_name: str,
        field_type: Type,
    ) -> bool:
        """Return True if a field should be hidden in the tree."""
        try:
            field_obj = next(f for f in fields(obj_type) if f.name == field_name)
            if "ui_hidden" in field_obj.metadata and bool(
                field_obj.metadata["ui_hidden"]
            ):
                return True
        except (StopIteration, TypeError):
            pass

        base_type = self.get_base_type(field_type)
        if is_ui_hidden_config_type(base_type):
            return True

        return False

    def get_base_type(self, obj_type: Type) -> Type:
        """Return the non-lazy base type for a dataclass.

        Lazy dataclass identity is provided by ObjectState's LazyDataclass base
        and registry, not by class-name shape.
        """
        if is_lazy_dataclass(obj_type):
            base_type = get_base_type_for_lazy(obj_type)
            if base_type is not None:
                return base_type
        return obj_type

    def activate_item(
        self,
        item: QTreeWidgetItem,
        *,
        scroll_to_section: ScrollToSection,
        field_for_class: FieldForClass,
    ) -> None:
        """Apply standard activation behavior for a tree widget item."""
        payload = self._item_payload(item)
        if payload is None:
            return
        activate_config_tree_item(
            payload,
            scroll_to_section=scroll_to_section,
            field_for_class=field_for_class,
        )

    def _item_payload(self, item: QTreeWidgetItem) -> ConfigTreeItemPayload | None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            return None
        if not isinstance(data, ConfigTreeItemPayload):
            raise TypeError(
                "Config tree item data must be ConfigTreeItemPayload; got "
                f"{type(data).__name__}."
            )
        return data

    def field_for_class_in_dataclass_instance(
        self,
        root_config,
        target_class: Type,
    ) -> str | None:
        """Find the root dataclass field that edits target_class."""
        if not is_dataclass(root_config):
            return None
        return self.field_for_class_in_dataclass_type(type(root_config), target_class)

    def field_for_class_in_dataclass_type(
        self,
        root_type: Type,
        target_class: Type,
    ) -> str | None:
        """Find the dataclass field whose annotation resolves to target_class."""
        for field in fields(root_type):
            if self.annotation_matches_class(field.type, target_class):
                return field.name
        return None

    def field_for_class_in_mapping(
        self,
        dataclass_params: Mapping[str, Type],
        target_class: Type,
    ) -> str | None:
        """Find the parameter name whose dataclass type resolves to target_class."""
        for field_name, obj_type in dataclass_params.items():
            if self.annotation_matches_class(obj_type, target_class):
                return field_name
        return None

    def annotation_matches_class(self, annotation, target_class: Type) -> bool:
        """Return True when a type annotation represents target_class."""
        for candidate_type in self._annotation_candidate_types(annotation):
            if candidate_type is target_class:
                return True
            if self.get_base_type(candidate_type) is target_class:
                return True
        return False

    def _annotation_candidate_types(self, annotation) -> Iterable[Type]:
        if isinstance(annotation, type):
            yield annotation
            return

        origin = get_origin(annotation)
        if origin in (Union, UnionType):
            for arg in get_args(annotation):
                if arg is not type(None) and isinstance(arg, type):
                    yield arg

    def add_inheritance_info(
        self,
        parent_item: QTreeWidgetItem,
        obj_type: Type,
    ) -> None:
        """Append inheritance information beneath the provided tree item."""
        direct_bases = []
        for cls in obj_type.__bases__:
            if cls.__name__ == "object":
                continue
            if not is_dataclass(cls):
                continue

            base_type = self.get_base_type(cls)
            direct_bases.append(base_type)

        for base_class in direct_bases:
            ui_hidden = is_ui_hidden_config_type(base_class)

            base_item = QTreeWidgetItem([base_class.__name__])
            base_item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                ConfigTreeItemPayload(
                    item_type=ConfigTreeItemKind.INHERITANCE_LINK,
                    target_class=base_class,
                    ui_hidden=ui_hidden,
                ),
            )

            if ui_hidden:
                font = base_item.font(0)
                font.setItalic(True)
                base_item.setFont(0, font)
                base_item.setForeground(0, QColor(128, 128, 128))
                base_item.setToolTip(0, self._INHERITANCE_TOOLTIP)

            parent_item.addChild(base_item)
            self.add_inheritance_info(base_item, base_class)
