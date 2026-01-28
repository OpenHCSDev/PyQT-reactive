"""
Preview Formatting Strategy Pattern

Provides pluggable formatting strategies for list item previews.
Separates data collection from presentation using builder pattern and config-driven styling.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Callable, TYPE_CHECKING, Dict, Any, Type, Union

if TYPE_CHECKING:
    from objectstate import ObjectState

from pyqt_reactive.widgets.shared.list_item_delegate import Segment


def get_group_abbreviation(config_type: Union[str, type]) -> str:
    """Look up group abbreviation from GROUP_ABBREVIATIONS_REGISTRY.

    Handles both type objects and type name strings.

    Args:
        config_type: Config class or type name to get abbreviation for

    Returns:
        Abbreviation string if found, otherwise falls back to class name prefix
    """
    from objectstate.lazy_factory import GROUP_ABBREVIATIONS_REGISTRY

    if isinstance(config_type, str):
        return config_type.split('_')[0] if config_type else "root"

    if config_type in GROUP_ABBREVIATIONS_REGISTRY:
        return GROUP_ABBREVIATIONS_REGISTRY[config_type]

    for base in config_type.__mro__[1:]:
        if base in GROUP_ABBREVIATIONS_REGISTRY:
            return GROUP_ABBREVIATIONS_REGISTRY[base]

    return config_type.__name__.split('_')[0]


@dataclass(frozen=True)
class FormattingConfig:
    """Presentation rules for preview formatting."""

    # Group configuration
    show_group_labels: bool = True
    group_separator: str = " | "

    # Field configuration
    # First field separator: empty for "{{" format (already in label)
    first_field_separator: str = ""
    field_separator: str = ", "
    closing_brace_separator: str = ""  # Separator after closing brace

    # Abbreviation strategy - looks up from GROUP_ABBREVIATIONS_REGISTRY
    container_abbr_func: Callable[[Union[str, type]], str] = get_group_abbreviation

    # Group label format
    # Format: "{abbr}{{" - abbreviation with opening brace
    # Example: "{abbr}{{" produces "wf{well_filter=2}"
    group_label_format: str = "{abbr}{{"  # e.g., "wf{" or "planning{"


@dataclass
class PreviewGroup:
    """A group of preview fields from same config type."""
    container_type: type  # Config type for this group (PathPlanningConfig, etc.)
    field_data: List[Tuple[str, Any, str]]  # (field_path, value, label)

    def __post_init__(self):
        """Validate container_type."""
        if self.container_type is None:
            raise ValueError("container_type cannot be None")


class PreviewSegmentBuilder:
    """Builds preview segments by grouping fields by their config type."""

    def __init__(self, formatting_config: FormattingConfig, state: Optional['ObjectState'] = None):
        self.config = formatting_config
        self.state = state
        self.groups: Dict[str, PreviewGroup] = {}
        self.group_order: List[str] = []  # Preserve insertion order

    def add_field(self, field_path: str, value: Any, label: str, container_type: type):
        """Add a field to its config type's group.

        Groups all fields by their container type.
        - Dataclass configs: use type name as group (e.g., 'PathPlanningConfig')
        - Primitive types (int, str, etc.): group as 'root'

        This ensures consistent grouping behavior for all fields.
        """
        from dataclasses import is_dataclass

        # Use config type name for dataclass configs, 'root' for primitives
        if is_dataclass(container_type):
            container_key = container_type.__name__
        else:
            container_key = "root"

        if container_key not in self.groups:
            self.groups[container_key] = PreviewGroup(container_type=container_type, field_data=[])
            self.group_order.append(container_key)

        self.groups[container_key].field_data.append((field_path, value, label))

    def build(self) -> List[Tuple[str, str, Optional[str]]]:
        """Render all groups using formatting config."""
        segments = []

        for i, container_key in enumerate(self.group_order):
            group = self.groups[container_key]

            # Render group
            group_segments = self._render_group(group, i == 0)
            segments.extend(group_segments)

        return segments

    def _render_group(self, group: PreviewGroup, is_first_group: bool) -> List[Tuple]:
        """Render a single group using config.

        Root group (primitive types) is rendered without braces or labels.
        Dataclass groups use abbreviation with braces.
        """
        import logging
        logger = logging.getLogger(__name__)

        segments = []
        container_key = group.container_type.__name__ if group.container_type else "root"
        is_root_group = container_key == "root"

        # Group separator BEFORE abbreviation (not after)
        group_sep_before_abbr = "" if is_first_group else self.config.group_separator

        # Group opening label (if configured and not root group)
        if self.config.show_group_labels and not is_root_group:
            abbr = self.config.container_abbr_func(group.container_type)
            # Add separator before abbreviation (for non-first groups)
            segments.append((abbr, str(group.container_type), group_sep_before_abbr))
            # Add opening brace (no separator before or after)
            segments.append(("{", None, ""))
            logger.debug(f"  Group: {group.container_type.__name__} -> {abbr}{{")

        # Fields in group
        for j, (field_path, value, label) in enumerate(group.field_data):
            if self.config.show_group_labels and not is_root_group:
                # First field: no separator (already in group label format "*{")
                # Subsequent fields: comma separator
                field_sep = "" if j == 0 else ", "
            else:
                # No group labels: use default separator between all fields
                field_sep = None if j == 0 else self.config.field_separator

            segments.append((label, field_path, field_sep))
            logger.debug(f"    Field: {field_path} -> {label}")

        # Closing brace for group (if showing group labels and not root group) - no styling
        if self.config.show_group_labels and not is_root_group and group.field_data:
            segments.append(("}", None, self.config.closing_brace_separator))
            logger.debug(f"  Closing brace: }}")

        return segments


class PreviewFormattingStrategy(ABC):
    """Abstract strategy for preview formatting."""

    def __init__(self, config: FormattingConfig, widget: Any = None):
        self.config = config
        self.widget = widget  # Widget instance for method lookups

    @abstractmethod
    def collect_and_render(
        self,
        state: Optional['ObjectState'],
        field_paths: List[str],
        formatters: dict,
        field_value_formatter: callable,
    ) -> List[Tuple[str, str, Optional[str]]]:
        """
        Collect field data and render segments.

        Returns:
            List of (label_text, field_path, sep_before) tuples
        """
        pass


class DefaultPreviewFormattingStrategy(PreviewFormattingStrategy):
    """Default strategy with grouping by config type."""

    def collect_and_render(
        self,
        state: Optional['ObjectState'],
        field_paths: List[str],
        formatters: dict,
        field_value_formatter: callable,
    ) -> List[Tuple[str, str, Optional[str]]]:
        """
        Collect field data using builder, then render.

        Returns:
            List of (label_text, field_path, sep_before) tuples
        """
        import logging
        logger = logging.getLogger(__name__)

        if state is None:
            logger.debug(f"📐 PREVIEW_FORMAT: state is None, returning []")
            return []

        # Phase 1: Collect data using builder
        builder = PreviewSegmentBuilder(self.config, state)

        for field_path in field_paths:
            value = state.get_resolved_value(field_path)
            if value is None:
                logger.debug(f"  ⏭️  Skipping {field_path}: value is None")
                continue

            # Get container type from state
            container_path = field_path.rsplit('.', 1)[0] if '.' in field_path else ""
            container_type = state._path_to_type.get(container_path, type(value))
            if container_type is None:
                container_type = type(value)
                logger.debug(f"  ⚠️  Container type from type(value) for {field_path}: {container_type.__name__}")
            else:
                logger.debug(f"  ✓ Container type from state for {field_path}: {container_type.__name__}")

            # Get label
            if field_path in formatters:
                label = self._apply_formatter(formatters[field_path], value, state, field_path)
            else:
                label = field_value_formatter(field_path, value)

            if label:
                logger.debug(f"  ✓ Added {field_path}: {label}, container_type={container_type.__name__}")
                builder.add_field(field_path, value, label, container_type)

        # Phase 2: Render
        segments = builder.build()
        logger.debug(f"📐 PREVIEW_FORMAT: {len(segments)} segments: {[(s[0][:30], s[1][:30] if len(s)>1 and s[1] else '') for s in segments[:5]]}")
        return segments

    def _apply_formatter(self, formatter, value, state, field_path):
        """Apply formatter to value."""
        if isinstance(formatter, str):
            # Look up method on widget, not self (strategy)
            formatter_method = getattr(self.widget, formatter, None)
            if formatter_method:
                import inspect
                sig = inspect.signature(formatter_method)
                if len(sig.parameters) >= 2:
                    return formatter_method(value, state)
                return formatter_method(value)
            return None  # Method not found - skip this field
        return formatter(value)  # formatter is callable - invoke it
