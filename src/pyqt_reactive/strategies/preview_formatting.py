"""
Preview Formatting Strategy Pattern

Provides pluggable formatting strategies for list item previews.
Separates data collection from presentation using builder pattern and config-driven styling.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Callable, TYPE_CHECKING, Dict, Any, Type, Union

if TYPE_CHECKING:
    from objectstate import ObjectState

from pyqt_reactive.widgets.shared.list_item_delegate import Segment

logging.getLogger(__name__).setLevel(logging.WARNING)


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
    """A group of fields from the same config type."""
    container_type: type
    field_data: List[Tuple[str, Any, str]]  # (field_path, value, label)
    container_key: str  # Store container key once to avoid recomputing

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
        import logging
        logger = logging.getLogger(__name__)
        from dataclasses import is_dataclass

        logger.info(f"add_field: field_path={field_path}, container_type={container_type.__name__ if container_type else None}")

        # Use config type name for dataclass configs, 'root' for primitives
        if is_dataclass(container_type):
            container_key = container_type.__name__
            logger.info(f"  Decision: is_dataclass -> container_key='{container_key}'")
        else:
            container_key = "root"
            logger.info(f"  Decision: NOT is_dataclass -> container_key='root'")

        if container_key not in self.groups:
            self.groups[container_key] = PreviewGroup(
                container_type=container_type,
                field_data=[],
                container_key=container_key
            )
            self.group_order.append(container_key)
            logger.info(f"  Created new group: '{container_key}' (total groups: {len(self.groups)})")
        else:
            logger.info(f"  Using existing group: '{container_key}'")

        self.groups[container_key].field_data.append((field_path, value, label))
        logger.info(f"  Added field to group '{container_key}' (now has {len(self.groups[container_key].field_data)} fields)")

    def build(self) -> List[Tuple[str, str, Optional[str]]]:
        """Render all groups using formatting config."""
        import logging
        logger = logging.getLogger(__name__)

        logger.info("=" * 60)
        logger.info(f"BUILD: Rendering {len(self.group_order)} groups")
        logger.info(f"group_order={self.group_order}")

        segments = []

        for i, container_key in enumerate(self.group_order):
            group = self.groups[container_key]
            logger.info(f"--- Rendering group {i+1}/{len(self.group_order)}: '{container_key}' ---")
            logger.info(f"  container_type={group.container_type.__name__ if group.container_type else None}")
            logger.info(f"  field_count={len(group.field_data)}")

            # Render group
            group_segments = self._render_group(group, i == 0)
            logger.info(f"  Generated {len(group_segments)} segments")
            segments.extend(group_segments)

        logger.info(f"BUILD COMPLETE: Total {len(segments)} segments")
        return segments

    def _render_group(self, group: PreviewGroup, is_first_group: bool) -> List[Tuple]:
        """Render a single group using config.

        Root group (primitive types) is rendered without braces or labels.
        Dataclass groups use abbreviation with braces.

        Uses stored container_key from PreviewGroup to avoid recomputing.
        """
        import logging
        logger = logging.getLogger(__name__)

        segments = []
        is_root_group = group.container_key == "root"  # Use stored key

        logger.info(f"  container_key='{group.container_key}', is_root_group={is_root_group}")
        logger.info(f"  show_group_labels={self.config.show_group_labels}, is_first_group={is_first_group}")

        # Group separator BEFORE abbreviation (not after)
        group_sep_before_abbr = "" if is_first_group else self.config.group_separator
        logger.info(f"  group_sep_before_abbr='{group_sep_before_abbr}'")

        # Group opening label (if configured)
        if self.config.show_group_labels:
            if is_root_group:
                # Root group gets 'root' label
                abbr = "root"
                abbr_field_path = None  # Root fields have varied paths, no single prefix
                logger.info(f"  Adding root abbr with field_path={abbr_field_path}")
            else:
                # Config groups get their abbreviation
                abbr = self.config.container_abbr_func(group.container_type)
                
                # Extract the field prefix from the first field in the group
                # e.g., from 'path_planning_config.sub_dir' -> 'path_planning_config'
                # This matches the format used by dirty_fields/sig_diff_fields
                if group.field_data:
                    first_field_path = group.field_data[0][0]
                    abbr_field_path = first_field_path.split('.')[0] if '.' in first_field_path else first_field_path
                else:
                    abbr_field_path = None
                
                logger.info(f"  Adding abbr '{abbr}' with field_path={abbr_field_path}")
            
            segments.append((abbr, abbr_field_path, group_sep_before_abbr))
            
            # Add opening brace (no separator before or after)
            segments.append(("{", None, ""))
            logger.info(f"  Added opening brace")
        else:
            logger.info(f"  SKIPPING abbr/brace: show_group_labels={self.config.show_group_labels}")

        # Fields in group
        logger.info(f"  Rendering {len(group.field_data)} fields")
        for j, (field_path, value, label) in enumerate(group.field_data):
            if self.config.show_group_labels:
                # First field: no separator (already in group label format "*{")
                # Subsequent fields: comma separator
                field_sep = "" if j == 0 else ", "
            else:
                # No group labels: use default separator between all fields
                field_sep = None if j == 0 else self.config.field_separator

            logger.info(f"    Field {j+1}: {field_path}, sep_before='{field_sep}'")
            segments.append((label, field_path, field_sep))

        # Closing brace for group (if showing group labels) - no styling
        if self.config.show_group_labels and group.field_data:
            segments.append(("}", None, self.config.closing_brace_separator))
            logger.info(f"  Added closing brace")
        else:
            if not self.config.show_group_labels:
                logger.info(f"  SKIPPING closing brace: show_group_labels=False")
            elif not group.field_data:
                logger.info(f"  SKIPPING closing brace: no fields")

        logger.info(f"  Total segments from this group: {len(segments)}")
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

        logger.info("=" * 60)
        logger.info(f"PREVIEW STRATEGY: Processing {len(field_paths)} field_paths")
        logger.info(f"show_group_labels={self.config.show_group_labels}")

        for i, field_path in enumerate(field_paths):
            logger.info(f"--- Field {i+1}/{len(field_paths)}: {field_path} ---")

            value = state.get_resolved_value(field_path)
            if value is None:
                logger.info(f"  ⏭️  SKIPPED: value is None")
                continue

            logger.info(f"  Value type: {type(value).__name__}, value={value}")

            # Get container type from state
            container_path = field_path.rsplit('.', 1)[0] if '.' in field_path else ""
            logger.info(f"  container_path='{container_path}'")
            logger.info(f"  state._path_to_type.keys()={list(state._path_to_type.keys())[:10]}")

            container_type = state._path_to_type.get(container_path, type(value))
            if container_type is None:
                container_type = type(value)
                logger.info(f"  ⚠️  FALLBACK: Container type from type(value)={container_type.__name__}")
            else:
                logger.info(f"  ✓ LOOKUP: Container type from state={container_type.__name__}")

            # Get label
            if field_path in formatters:
                label = self._apply_formatter(formatters[field_path], value, state, field_path)
                logger.info(f"  Using formatter for {field_path}: {label}")
            else:
                label = field_value_formatter(field_path, value)
                logger.info(f"  Using field_value_formatter for {field_path}: {label}")

            if label:
                logger.info(f"  ✓ CALLING builder.add_field({field_path}, {type(value).__name__}, {container_type.__name__})")
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
