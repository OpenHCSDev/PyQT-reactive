"""Magicgui-based PyQt6 Widget Creation with OpenHCS Extensions"""

import dataclasses
import logging
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Type, Callable, get_origin

from PyQt6.QtWidgets import QCheckBox, QLineEdit, QComboBox, QGroupBox, QVBoxLayout, QSpinBox, QDoubleSpinBox, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIntValidator, QValidator
from magicgui.widgets import Widget as MagicGuiWidget, create_widget
from magicgui.type_map import register_type

from pyqt_reactive.widgets import (
    NoScrollSpinBox, NoScrollDoubleSpinBox, NoScrollComboBox, NoneAwareCheckBox
)
from pyqt_reactive.protocols import PyQtWidgetMeta, ValueGettable, ValueSettable, ChangeSignalEmitter
from pyqt_reactive.protocols.widget_adapters import CheckboxGroupAdapter
from pyqt_reactive.widgets.enhanced_path_widget import EnhancedPathWidget
from pyqt_reactive.theming.color_scheme import ColorScheme as PyQt6ColorScheme
from pyqt_reactive.forms.widget_creation_registry import (
    enum_member_type,
    resolve_optional,
    is_enum,
    is_list_of_enums,
    get_enum_from_list,
)
from contextlib import contextmanager

try:
    from pyqt_reactive.core.performance_monitor import timer
except Exception:  # pragma: no cover - optional performance monitoring
    @contextmanager
    def timer(*args, **kwargs):
        yield

logger = logging.getLogger(__name__)


# ==================== None-Aware Widget Classes ====================
# Defined at top so they can be used throughout this file.

class NoneAwareLineEdit(
    QLineEdit,
    ValueGettable,
    ValueSettable,
    metaclass=PyQtWidgetMeta,
):
    """QLineEdit that properly handles None values for lazy dataclass contexts."""

    def get_value(self):
        """Get value, returning None for empty text instead of empty string."""
        text = self.text().strip()
        return None if text == "" else text

    def set_value(self, value):
        """Set value, handling None properly."""
        self.setText("" if value is None else str(value))


class NoneAwareIntEdit(
    QLineEdit,
    ValueGettable,
    ValueSettable,
    metaclass=PyQtWidgetMeta,
):
    """QLineEdit that only allows digits and properly handles None values for integer fields."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setValidator(QIntValidator())

    def get_value(self):
        """Get value, returning None for empty text or converting to int."""
        text = self.text().strip()
        if text == "":
            return None
        validator = self.validator()
        if validator is None:
            raise TypeError("NoneAwareIntEdit requires a QIntValidator before value extraction")
        state, _, _ = validator.validate(text, 0)
        if state != QValidator.State.Acceptable:
            raise ValueError(f"Invalid integer text in NoneAwareIntEdit: {text!r}")
        return int(text)

    def set_value(self, value):
        """Set value, handling None properly."""
        self.setText("" if value is None else str(value))


@dataclasses.dataclass(frozen=True)
class WidgetConfig:
    """Immutable widget configuration constants."""
    NUMERIC_RANGE_MIN: int = -999999
    NUMERIC_RANGE_MAX: int = 999999
    FLOAT_PRECISION: int = 15  # Practical limit for double precision (effectively unlimited)


def create_enhanced_path_widget(param_name: str = "", current_value: Any = None, parameter_info: Any = None):
    """Factory function for OpenHCS enhanced path widgets."""
    return EnhancedPathWidget(param_name, current_value, parameter_info, PyQt6ColorScheme())


def _create_none_aware_int_widget():
    """Factory function for NoneAwareIntEdit widgets."""
    return NoneAwareIntEdit()


def _create_none_aware_checkbox():
    """Factory function for NoneAwareCheckBox widgets."""
    from pyqt_reactive.widgets import NoneAwareCheckBox
    return NoneAwareCheckBox()


def _create_direct_int_widget(current_value: Any = None):
    """Fast path: Create int widget directly without magicgui overhead."""
    widget = NoneAwareIntEdit()
    if current_value is not None:
        widget.set_value(current_value)
    return widget


def _create_direct_float_widget(current_value: Any = None):
    """Fast path: Create float widget directly without magicgui overhead."""
    widget = NoScrollDoubleSpinBox()
    widget.setRange(WidgetConfig.NUMERIC_RANGE_MIN, WidgetConfig.NUMERIC_RANGE_MAX)
    widget.setDecimals(WidgetConfig.FLOAT_PRECISION)
    if current_value is not None:
        widget.setValue(float(current_value))
    else:
        widget.clear()
    return widget


def _create_direct_bool_widget(current_value: Any = None):
    """Fast path: Create bool widget directly without magicgui overhead."""
    from pyqt_reactive.widgets import NoneAwareCheckBox
    widget = NoneAwareCheckBox()
    if current_value is not None:
        widget.setChecked(bool(current_value))
    return widget


def convert_widget_value_to_type(value: Any, param_type: Type) -> Any:
    """
    PyQt-specific type conversions for widget values.

    Handles conversions that are specific to how PyQt widgets represent values
    (e.g., Path widgets return strings, tuple/list fields are edited as string literals).

    Args:
        value: The raw value from the widget
        param_type: The target parameter type

    Returns:
        The converted value ready for the service layer
    """
    # Handle Path widgets - they return strings that need conversion
    try:
        if param_type is Path and isinstance(value, str):
            return Path(value) if value else None
    except Exception:
        pass

    # Handle tuple/list typed configs written as strings in UI
    try:
        from typing import get_origin, get_args
        import ast
        origin = get_origin(param_type)
        args = get_args(param_type)
        if origin in (tuple, list) and isinstance(value, str):
            # Safely parse string literal into Python object
            try:
                parsed = ast.literal_eval(value)
            except Exception:
                return value  # Return original if parse fails
            if parsed is not None:
                # Coerce to the annotated container type
                if origin is tuple:
                    parsed = tuple(parsed if isinstance(parsed, (list, tuple)) else [parsed])
                elif origin is list and not isinstance(parsed, list):
                    parsed = [parsed]
                # Optionally enforce inner type if annotated
                if args:
                    inner = args[0]
                    try:
                        parsed = tuple(inner(x) for x in parsed) if origin is tuple else [inner(x) for x in parsed]
                    except Exception:
                        pass
                return parsed
    except Exception:
        pass

    return value


def register_openhcs_widgets():
    """Register OpenHCS custom widgets with magicgui type system."""
    # Register using string widget types that magicgui recognizes
    register_type(int, widget_type="SpinBox")
    register_type(float, widget_type="FloatSpinBox")
    register_type(Path, widget_type="FileEdit")


# Functional widget replacement registry
WIDGET_REPLACEMENT_REGISTRY: Dict[Type, callable] = {
    str: lambda current_value, **kwargs: create_string_fallback_widget(current_value=current_value),
    bool: lambda current_value, **kwargs: (
        lambda w: (w.set_value(current_value), w)[1]
    )(_create_none_aware_checkbox()),
    int: lambda current_value, **kwargs: (
        lambda w: (w.set_value(current_value), w)[1]
    )(_create_none_aware_int_widget()),
    float: lambda current_value, **kwargs: (
        lambda w: (w.setValue(float(current_value)), w)[1] if current_value is not None else w
    )(NoScrollDoubleSpinBox()),
    Path: lambda current_value, param_name, parameter_info, **kwargs:
        create_enhanced_path_widget(param_name, current_value, parameter_info),
}

# String fallback widget for any type magicgui cannot handle
def create_string_fallback_widget(current_value: Any, **kwargs) -> QLineEdit:
    """Create string fallback widget for unsupported types."""
    widget = NoneAwareLineEdit()
    widget.set_value(current_value)
    return widget


def create_enum_widget_unified(enum_type: Type, current_value: Any, **kwargs) -> QComboBox:
    """Unified enum widget creator with consistent display text."""
    from pyqt_reactive.forms.ui_utils import format_enum_display

    widget = NoScrollComboBox()

    # Add all enum items
    for enum_value in enum_type:
        display_text = format_enum_display(enum_value)
        widget.addItem(display_text, enum_value)

    # Set current selection
    if current_value and isinstance(current_value, enum_type):
        _select_combobox_data(widget, current_value)

    return widget


def _select_combobox_data(widget: QComboBox, value: Any) -> None:
    """Select the first combobox entry whose item data matches value."""
    for index in range(widget.count()):
        if widget.itemData(index) == value:
            widget.setCurrentIndex(index)
            return


def _type_label(param_type: Type) -> str:
    """Return a stable label for diagnostics and timer names."""
    return param_type.__name__ if isinstance(param_type, type) else str(param_type)


def create_pyqt6_widget(param_name: str, param_type: Type, current_value: Any,
                       widget_id: str, parameter_info: Any = None) -> Any:
    """Create a PyQt6 widget using the functional widget strategy."""
    with timer("            resolve_optional", threshold_ms=0.1):
        resolved_type = resolve_optional(param_type)
        enum_type = enum_member_type(resolved_type)
        if enum_type is not None:
            resolved_type = enum_type

    # Handle direct List[Enum] types - create multi-selection checkbox group
    if is_list_of_enums(resolved_type):
        with timer("            create checkbox group", threshold_ms=0.5):
            return _create_checkbox_group_widget(param_name, resolved_type, current_value)

    # Extract enum from list wrapper for other cases
    with timer("            extract enum value", threshold_ms=0.1):
        extracted_value = (current_value[0] if isinstance(current_value, list) and
                          len(current_value) == 1 and isinstance(current_value[0], Enum)
                          else current_value)

    # Handle direct enum types
    if is_enum(resolved_type):
        with timer("            create enum widget", threshold_ms=0.5):
            return create_enum_widget_unified(resolved_type, extracted_value)

    # OPTIMIZATION: Fast path for simple types - bypass magicgui overhead (~0.3ms per widget)
    # This saves ~36ms for 120 widgets
    if resolved_type == int:
        with timer("            create int widget (fast path)", threshold_ms=0.5):
            return _create_direct_int_widget(extracted_value)
    elif resolved_type == float:
        with timer("            create float widget (fast path)", threshold_ms=0.5):
            return _create_direct_float_widget(extracted_value)
    elif resolved_type == bool:
        with timer("            create bool widget (fast path)", threshold_ms=0.5):
            return _create_direct_bool_widget(extracted_value)
    elif resolved_type == str:
        with timer("            create string widget (fast path)", threshold_ms=0.5):
            return create_string_fallback_widget(current_value=extracted_value)

    # Check for OpenHCS custom widget replacements
    with timer("            registry lookup", threshold_ms=0.1):
        replacement_factory = WIDGET_REPLACEMENT_REGISTRY.get(resolved_type)

    if replacement_factory:
        with timer(f"            call replacement factory for {_type_label(resolved_type)}", threshold_ms=0.5):
            widget = replacement_factory(
                current_value=extracted_value,
                param_name=param_name,
                parameter_info=parameter_info
            )
    else:
        # Try magicgui for complex types, with string fallback for unsupported types
        try:
            # Handle None values to prevent magicgui from converting None to literal "None" string
            with timer("            prepare magicgui value", threshold_ms=0.1):
                magicgui_value = extracted_value
                if extracted_value is None:
                    # Use appropriate default values for magicgui to prevent "None" string conversion
                    # CRITICAL FIX: Use minimal defaults that won't look like concrete user values
                    if resolved_type == int:
                        magicgui_value = 0  # magicgui needs a value, placeholder will override display
                    elif resolved_type == float:
                        magicgui_value = 0.0  # magicgui needs a value, placeholder will override display
                    elif resolved_type == bool:
                        magicgui_value = False
                    elif get_origin(resolved_type) is list:
                        magicgui_value = []  # Empty list for List[T] types
                    elif get_origin(resolved_type) is tuple:
                        magicgui_value = ()  # Empty tuple for tuple[T, ...] types
                    # For other types, let magicgui handle None (might still cause issues but less common)

            with timer(f"            magicgui.create_widget({param_name}, {_type_label(resolved_type)})", threshold_ms=0.0):
                widget = create_widget(annotation=resolved_type, value=magicgui_value)

            # Check if magicgui returned a basic QWidget (which indicates failure)
            with timer("            check magicgui result", threshold_ms=0.1):
                native_widget = widget.native if isinstance(widget, MagicGuiWidget) else None
                if isinstance(native_widget, QWidget) and type(native_widget) is QWidget:
                    logger.warning(f"magicgui returned basic QWidget for {param_name} ({resolved_type}), using fallback")
                    widget = create_string_fallback_widget(current_value=extracted_value)
                elif type(widget) is QWidget:
                    logger.warning(f"magicgui returned basic QWidget for {param_name} ({resolved_type}), using fallback")
                    widget = create_string_fallback_widget(current_value=extracted_value)
                else:
                    # If original value was None, clear the widget to show placeholder behavior
                    if extracted_value is None and native_widget is not None:
                        if isinstance(native_widget, QLineEdit):
                            native_widget.setText("")  # Clear text for None values
                        elif isinstance(native_widget, QCheckBox) and resolved_type == bool:
                            native_widget.setChecked(False)  # Uncheck for None bool values

                    # Extract native PyQt6 widget from magicgui wrapper if needed
                    if native_widget is not None:
                        native_widget.setProperty("magicgui_widget", widget)
                        widget = native_widget
        except Exception as e:
            # Fallback to string widget for any type magicgui cannot handle
            # Use DEBUG level since this is expected for complex Union types (e.g., well_filter)
            logger.debug(f"Widget creation failed for {param_name} ({resolved_type}): {e}")
            widget = create_string_fallback_widget(current_value=extracted_value)

    return widget


def _create_checkbox_group_widget(param_name: str, param_type: Type, current_value: Any):
    """Create multi-selection checkbox group for List[Enum] parameters."""
    from pyqt_reactive.widgets import NoneAwareCheckBox
    from pyqt_reactive.protocols.widget_adapters import CheckboxGroupAdapter

    enum_type = get_enum_from_list(param_type)
    widget = CheckboxGroupAdapter()
    # Don't set title - label is added separately in widget_creation_config.py
    # Transparent background so parent's scope-tinted background shows through
    widget.setStyleSheet("QGroupBox { background-color: transparent; border: none; }")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(4, 2, 4, 2)  # Minimal margins for checkbox group
    layout.setSpacing(2)

    # Populate checkboxes for each enum value
    for enum_value in enum_type:
        checkbox = NoneAwareCheckBox()
        checkbox.setText(enum_value.value)
        checkbox.setObjectName(f"{param_name}_{enum_value.value}")
        widget._checkboxes[enum_value] = checkbox
        layout.addWidget(checkbox)

    # Set current value using ABC method
    widget.set_value(current_value)

    return widget


class PlaceholderConfig:
    """Declarative placeholder configuration."""
    PLACEHOLDER_PREFIX = "Pipeline default: "
    # Stronger styling that overrides application theme
    PLACEHOLDER_STYLE = "color: #888888 !important; font-style: italic !important; opacity: 0.7;"
    INTERACTION_HINTS = {
        'checkbox': 'click to set your own value',
        'combobox': 'select to set your own value'
    }


def _get_cached_placeholder_text(widget: QWidget) -> str | None:
    """Return cached placeholder text stored on the Qt object."""
    cached = widget.property("cached_placeholder_text")
    return cached if isinstance(cached, str) else None


def _set_cached_placeholder_text(widget: QWidget, placeholder_text: str) -> None:
    """Store cached placeholder text on the Qt object."""
    widget.setProperty("cached_placeholder_text", placeholder_text)


def _clear_cached_placeholder_text(widget: QWidget) -> None:
    """Clear cached placeholder text stored on the Qt object."""
    widget.setProperty("cached_placeholder_text", None)


class PlaceholderRenderer:
    """Typed placeholder rendering authority for PyQt widgets."""

    def extract_default_value(self, placeholder_text: str) -> str:
        if ':' in placeholder_text:
            value = placeholder_text.split(':', 1)[1].strip()
        else:
            value = placeholder_text.strip()

        if '.' in value and not value.startswith('('):
            enum_parts = value.split('.')
            if len(enum_parts) == 2:
                return enum_parts[1]

        return value

    def apply_styling(self, widget: QWidget, interaction_hint: str, placeholder_text: str) -> None:
        """Apply consistent placeholder styling and tooltip."""
        if isinstance(widget, QComboBox):
            if widget.isEditable():
                style = """
                    QComboBox QLineEdit {
                        color: #888888 !important;
                        font-style: italic !important;
                    }
                """
            else:
                style = """
                    QComboBox {
                        color: #888888 !important;
                        font-style: italic !important;
                        opacity: 0.7;
                    }
                """
        elif isinstance(widget, QCheckBox):
            style = """
                QCheckBox {
                    color: #888888 !important;
                    font-style: italic !important;
                    opacity: 0.7;
                }
            """
        else:
            style = PlaceholderConfig.PLACEHOLDER_STYLE

        widget.setStyleSheet(style)
        widget.setToolTip(f"{placeholder_text} ({interaction_hint})")
        widget.setProperty("is_placeholder_state", True)

    def apply_lineedit(self, widget: QLineEdit, text: str) -> None:
        """Apply placeholder to line edit with proper state tracking."""
        was_blocked = widget.blockSignals(True)
        try:
            widget.clear()
            widget.setPlaceholderText(text)
        finally:
            widget.blockSignals(was_blocked)
        widget.setProperty("is_placeholder_state", True)
        widget.setToolTip(text)

    def apply_spinbox(self, widget: QSpinBox | QDoubleSpinBox, text: str) -> None:
        """Apply placeholder to spinbox showing full placeholder text with prefix."""
        was_blocked = widget.blockSignals(True)
        try:
            widget.setSpecialValueText(text)
            widget.setValue(widget.minimum())
        finally:
            widget.blockSignals(was_blocked)

        self.apply_styling(widget, 'change value to set your own', text)

    def apply_checkbox(self, widget: QCheckBox, placeholder_text: str) -> None:
        """Apply checkbox placeholder from a boolean placeholder value."""
        try:
            default_value = self.extract_default_value(placeholder_text).lower() == 'true'

            was_blocked = widget.blockSignals(True)
            try:
                widget.setChecked(default_value)
                if isinstance(widget, NoneAwareCheckBox):
                    widget.set_placeholder_preview(default_value)
            finally:
                widget.blockSignals(was_blocked)

            widget.setToolTip(f"{placeholder_text} ({PlaceholderConfig.INTERACTION_HINTS['checkbox']})")
            widget.setProperty("is_placeholder_state", True)
            widget.update()
        except Exception:
            widget.setToolTip(placeholder_text)

    def apply_checkbox_group_with_value(
        self,
        widget: CheckboxGroupAdapter,
        resolved_value: Any,
        placeholder_text: str
    ) -> None:
        """Apply checkbox-group placeholder from the resolved enum list."""
        try:
            if resolved_value is None:
                inherited_enums = []
            elif isinstance(resolved_value, list):
                inherited_enums = resolved_value
            else:
                raise TypeError(f"Checkbox group placeholder requires list or None, got {type(resolved_value).__name__}")

            for enum_value, checkbox in widget.checkbox_items():
                individual_placeholder = f"Pipeline default: {enum_value in inherited_enums}"
                self.apply_checkbox(checkbox, individual_placeholder)

            widget.setProperty("is_placeholder_state", True)
            widget.setToolTip(f"{placeholder_text} (click any checkbox to set your own value)")
        except Exception:
            logger.exception("Failed to apply checkbox group placeholder")
            widget.setToolTip(placeholder_text)

    def apply_path_widget(self, widget: EnhancedPathWidget, placeholder_text: str) -> None:
        """Apply placeholder to Path widget by targeting the inner QLineEdit."""
        was_blocked = widget.path_input.blockSignals(True)
        try:
            widget.path_input.clear()
            widget.path_input.setPlaceholderText(placeholder_text)
        finally:
            widget.path_input.blockSignals(was_blocked)
        widget.path_input.setProperty("is_placeholder_state", True)
        widget.path_input.setToolTip(placeholder_text)

    def apply_combobox(self, widget: QComboBox, placeholder_text: str) -> None:
        """Apply placeholder to combobox while preserving None as no concrete selection."""
        try:
            default_value = self.extract_default_value(placeholder_text)
            matching_index = next(
                (i for i in range(widget.count())
                 if _item_matches_value(widget, i, default_value)),
                -1
            )
            placeholder_display = (
                widget.itemText(matching_index) if matching_index >= 0 else default_value
            )

            was_blocked = widget.blockSignals(True)
            try:
                widget.setCurrentIndex(-1)

                if isinstance(widget, NoScrollComboBox):
                    widget.setPlaceholder(placeholder_display)
                elif widget.isEditable():
                    widget.lineEdit().setPlaceholderText(placeholder_display)
                else:
                    raise TypeError(
                        f"{type(widget).__name__} cannot display placeholder text without "
                        "NoScrollComboBox placeholder support or an editable line edit"
                    )
            finally:
                widget.blockSignals(was_blocked)

            widget.setToolTip(f"{placeholder_text} ({PlaceholderConfig.INTERACTION_HINTS['combobox']})")
            widget.setProperty("is_placeholder_state", True)
        except Exception:
            widget.setToolTip(placeholder_text)


PLACEHOLDER_RENDERER = PlaceholderRenderer()


def _item_matches_value(widget: QComboBox, index: int, target_value: str) -> bool:
    """Check if combobox item matches target value using robust enum matching."""
    item_data = widget.itemData(index)
    item_text = widget.itemText(index)
    target_normalized = target_value.upper()

    # Primary: Match enum name (most reliable)
    if isinstance(item_data, Enum):
        if item_data.name.upper() == target_normalized:
            return True

    # Secondary: Match enum value (case-insensitive)
    if isinstance(item_data, Enum):
        if str(item_data.value).upper() == target_normalized:
            return True

    # Tertiary: Match display text (case-insensitive)
    if item_text.upper() == target_normalized:
        return True

    return False


# Declarative widget-to-strategy mapping
WIDGET_PLACEHOLDER_STRATEGIES: Dict[Type, Callable[[Any, str], None]] = {
    QCheckBox: PLACEHOLDER_RENDERER.apply_checkbox,
    QComboBox: PLACEHOLDER_RENDERER.apply_combobox,
    QSpinBox: PLACEHOLDER_RENDERER.apply_spinbox,
    QDoubleSpinBox: PLACEHOLDER_RENDERER.apply_spinbox,
    NoScrollSpinBox: PLACEHOLDER_RENDERER.apply_spinbox,
    NoScrollDoubleSpinBox: PLACEHOLDER_RENDERER.apply_spinbox,
    NoScrollComboBox: PLACEHOLDER_RENDERER.apply_combobox,
    QLineEdit: PLACEHOLDER_RENDERER.apply_lineedit,
    NoneAwareIntEdit: PLACEHOLDER_RENDERER.apply_lineedit,
}

# Add Path widget support dynamically to avoid import issues
def _register_path_widget_strategy():
    """Register Path widget strategy dynamically to avoid circular imports."""
    try:
        from pyqt_reactive.widgets.enhanced_path_widget import EnhancedPathWidget
        WIDGET_PLACEHOLDER_STRATEGIES[EnhancedPathWidget] = PLACEHOLDER_RENDERER.apply_path_widget
    except ImportError:
        pass  # Path widget not available

def _register_none_aware_lineedit_strategy():
    """Register NoneAwareLineEdit strategy."""
    WIDGET_PLACEHOLDER_STRATEGIES[NoneAwareLineEdit] = PLACEHOLDER_RENDERER.apply_lineedit

def _register_none_aware_checkbox_strategy():
    """Register NoneAwareCheckBox strategy dynamically to avoid circular imports."""
    try:
        from pyqt_reactive.widgets import NoneAwareCheckBox
        WIDGET_PLACEHOLDER_STRATEGIES[NoneAwareCheckBox] = PLACEHOLDER_RENDERER.apply_checkbox
    except ImportError:
        pass  # NoneAwareCheckBox not available

# Register widget strategies
_register_path_widget_strategy()
_register_none_aware_lineedit_strategy()
_register_none_aware_checkbox_strategy()

@dataclasses.dataclass(frozen=True)
class PyQt6WidgetEnhancer:
    """Widget enhancement using functional dispatch patterns."""

    @staticmethod
    def apply_placeholder_text(widget: Any, placeholder_text: str) -> None:
        """Apply placeholder using declarative widget-strategy mapping."""
        # PERFORMANCE OPTIMIZATION: Skip if placeholder text is unchanged
        # This avoids redundant widget updates during sibling refresh cascades
        if not isinstance(widget, QWidget):
            raise TypeError(f"Placeholder support requires QWidget, got {type(widget).__name__}")

        cached_placeholder = _get_cached_placeholder_text(widget)
        if cached_placeholder == placeholder_text:
            return  # No change needed

        if isinstance(widget, CheckboxGroupAdapter):
            raise TypeError("Checkbox group placeholders require apply_placeholder_with_value")

        # Direct widget type mapping for enhanced placeholders
        widget_strategy = WIDGET_PLACEHOLDER_STRATEGIES.get(type(widget))
        if widget_strategy:
            widget_strategy(widget, placeholder_text)
            _set_cached_placeholder_text(widget, placeholder_text)
            return

        raise TypeError(
            f"Widget {type(widget).__name__} has no registered placeholder strategy"
        )

    @staticmethod
    def apply_placeholder_with_value(widget: Any, resolved_value: Any, placeholder_text: str) -> None:
        """Apply placeholder using actual resolved value for type-safe handling.
        
        This method passes the actual value (not just formatted text) to enable
        type-safe widget updates without string parsing.
        
        Args:
            widget: The widget to apply placeholder to
            resolved_value: The actual resolved value (e.g., List[Enum], bool, etc.)
            placeholder_text: Formatted placeholder text for display/tooltip
        """
        # PERFORMANCE OPTIMIZATION: Skip if placeholder text is unchanged
        if not isinstance(widget, QWidget):
            raise TypeError(f"Placeholder support requires QWidget, got {type(widget).__name__}")

        cached_placeholder = _get_cached_placeholder_text(widget)
        if cached_placeholder == placeholder_text:
            return  # No change needed

        # Check for checkbox group (QGroupBox with _checkboxes attribute)
        # Use type-safe value directly instead of parsing text
        if isinstance(widget, CheckboxGroupAdapter):
            PLACEHOLDER_RENDERER.apply_checkbox_group_with_value(widget, resolved_value, placeholder_text)
            _set_cached_placeholder_text(widget, placeholder_text)
            return

        # For other widgets, fall back to text-based placeholder
        PyQt6WidgetEnhancer.apply_placeholder_text(widget, placeholder_text)

    @staticmethod
    def apply_global_config_placeholder(widget: Any, field_name: str, global_config: Any = None) -> None:
        """
        Apply placeholder to standalone widget using global config.

        This method allows applying placeholders to widgets that are not part of
        a dataclass form by directly using the global configuration.

        Args:
            widget: The widget to apply placeholder to
            field_name: Name of the field in the global config
            global_config: Global config instance (uses thread-local if None)
        """
        try:
            if global_config is None:
                return  # No global config available

            if not dataclasses.is_dataclass(global_config):
                return

            field_names = {field.name for field in dataclasses.fields(global_config)}
            if field_name in field_names:
                field_value = object.__getattribute__(global_config, field_name)

                # Format the placeholder text appropriately for different types
                if isinstance(field_value, Enum):
                    from pyqt_reactive.forms.ui_utils import format_enum_placeholder
                    placeholder_text = format_enum_placeholder(field_value)
                else:
                    placeholder_text = f"Pipeline default: {field_value}"

                PyQt6WidgetEnhancer.apply_placeholder_text(widget, placeholder_text)
        except Exception:
            # Silently fail if placeholder can't be applied
            pass

    @staticmethod
    def connect_change_signal(widget: Any, param_name: str, callback: Any) -> None:
        """Connect signal with placeholder state management."""
        magicgui_widget = PyQt6WidgetEnhancer._get_magicgui_wrapper(widget)

        # Create placeholder-aware callback wrapper
        def create_wrapped_callback(original_callback, value_getter):
            def wrapped():
                PyQt6WidgetEnhancer._clear_placeholder_state(widget)
                original_callback(param_name, value_getter())
            return wrapped

        # Prioritize magicgui signals
        if isinstance(magicgui_widget, MagicGuiWidget):
            magicgui_widget.changed.connect(
                create_wrapped_callback(callback, lambda: magicgui_widget.value)
            )
            return

        # Check for CheckboxGroupAdapter using isinstance (anti-duck-typing)
        if isinstance(widget, CheckboxGroupAdapter):
            placeholder_aware_callback = lambda pn, val: (
                PyQt6WidgetEnhancer._clear_placeholder_state(widget),
                callback(pn, val)
            )[-1]
            PyQt6WidgetEnhancer._connect_checkbox_group_signals(widget, param_name, placeholder_aware_callback)
            return

        if isinstance(widget, ChangeSignalEmitter):
            def emit_contract_value(value):
                PyQt6WidgetEnhancer._clear_placeholder_state(widget)
                callback(param_name, value)

            widget.connect_change_signal(emit_contract_value)
            return

        placeholder_aware_callback = lambda value: (
            PyQt6WidgetEnhancer._clear_placeholder_state(widget),
            callback(param_name, value)
        )[-1]

        if isinstance(widget, QCheckBox):
            widget.stateChanged.connect(lambda: placeholder_aware_callback(widget.isChecked()))
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(
                lambda value: placeholder_aware_callback(
                    widget.get_value() if isinstance(widget, ValueGettable) else value
                )
            )
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(placeholder_aware_callback)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(lambda: placeholder_aware_callback(widget.currentData()))
        elif isinstance(widget, EnhancedPathWidget):
            widget.path_changed.connect(placeholder_aware_callback)
        else:
            raise ValueError(f"Widget {type(widget).__name__} has no supported change signal")

    @staticmethod
    def _connect_checkbox_group_signals(widget: Any, param_name: str, callback: Any) -> None:
        """Connect signals for checkbox group widgets.

        Treats List[Enum] like a list of independent bools:
        - When user clicks ANY checkbox, ALL checkboxes convert from placeholder to concrete
        - This ensures the entire list becomes concrete once the user starts editing
        """
        import logging
        logger = logging.getLogger(__name__)

        if isinstance(widget, CheckboxGroupAdapter):
            # Connect to each checkbox's stateChanged signal
            for checkbox in widget.checkbox_widgets():
                def make_handler(cb):
                    """Create handler with proper closure to avoid lambda capture issues."""
                    def handler(state):
                        # CRITICAL: When user clicks ANY checkbox, convert ALL checkboxes to concrete
                        # This implements "list of bools" behavior - editing one makes the whole list concrete
                        for other_checkbox in widget.checkbox_widgets():
                            other_checkbox.convert_placeholder_to_concrete()

                        # Clear placeholder state from the group widget itself
                        PyQt6WidgetEnhancer._clear_placeholder_state(widget)

                        # Get selected values (now all concrete) using ABC method
                        selected = widget.get_value()
                        # Handle None (placeholder state) in logging
                        selected_str = "None (inherit from parent)" if selected is None else [v.name for v in selected]
                        logger.debug(
                            "Checkbox %s changed to %s, selected values: %s",
                            cb.text(),
                            state,
                            selected_str,
                        )

                        callback(param_name, selected)
                    return handler

                checkbox.stateChanged.connect(make_handler(checkbox))

    @staticmethod
    def _clear_placeholder_state(widget: Any) -> None:
        """Clear placeholder state using functional approach."""
        # Handle checkbox groups by clearing each checkbox's placeholder state
        if isinstance(widget, CheckboxGroupAdapter):
            for checkbox in widget.checkbox_widgets():
                # CRITICAL FIX: Always clear cached placeholder text first, even if
                # the checkbox is not in placeholder state. This ensures resetting to
                # None will properly reapply the placeholder (not skip due to cache hit).
                checkbox.clear_placeholder_cache()
                if checkbox.property("is_placeholder_state"):
                    checkbox.setStyleSheet("")
                    checkbox.setProperty("is_placeholder_state", False)
                    checkbox.convert_placeholder_to_concrete()
                    # Clean checkbox tooltip
                    current_tooltip = checkbox.toolTip()
                    cleaned_tooltip = next(
                        (current_tooltip.replace(f" ({hint})", "")
                         for hint in PlaceholderConfig.INTERACTION_HINTS.values()
                         if f" ({hint})" in current_tooltip),
                        current_tooltip
                    )
                    checkbox.setToolTip(cleaned_tooltip)
            # Clear group widget's placeholder state and cache
            widget.setProperty("is_placeholder_state", False)
            widget.setToolTip("")
            _clear_cached_placeholder_text(widget)
            return

        # CRITICAL FIX: Always clear cached placeholder text when exiting placeholder state.
        # This ensures that resetting to None will properly reapply the placeholder
        # (not skip due to cache hit). The cache must be cleared even if the widget
        # is already in non-placeholder state (e.g., user clicked checkbox).
        _clear_cached_placeholder_text(widget)

        if not widget.property("is_placeholder_state"):
            return

        widget.setStyleSheet("")
        widget.setProperty("is_placeholder_state", False)

        # Clean tooltip using functional pattern
        current_tooltip = widget.toolTip()
        cleaned_tooltip = next(
            (current_tooltip.replace(f" ({hint})", "")
             for hint in PlaceholderConfig.INTERACTION_HINTS.values()
             if f" ({hint})" in current_tooltip),
            current_tooltip
        )
        widget.setToolTip(cleaned_tooltip)

    @staticmethod
    def _get_magicgui_wrapper(widget: Any) -> Any:
        """Get magicgui wrapper if widget was created by magicgui."""
        if isinstance(widget, QWidget):
            wrapper = widget.property("magicgui_widget")
            if isinstance(wrapper, MagicGuiWidget):
                return wrapper
        if isinstance(widget, MagicGuiWidget):
            return widget
        return None

    @staticmethod
    def set_widget_value(widget: Any, value: Any) -> None:
        """
        Set widget value without triggering signals.

        Args:
            widget: Widget to update
            value: New value
        """
        # Temporarily block signals to avoid recursion
        widget.blockSignals(True)

        try:
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, (QSpinBox, NoScrollSpinBox)):
                widget.setValue(int(value) if value is not None else 0)
            elif isinstance(widget, (QDoubleSpinBox, NoScrollDoubleSpinBox)):
                widget.setValue(float(value) if value is not None else 0.0)
            elif isinstance(widget, (QComboBox, NoScrollComboBox)):
                _select_combobox_data(widget, value)
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value) if value is not None else "")
            # Handle magicgui widgets
            elif isinstance(widget, MagicGuiWidget):
                widget.value = value
        finally:
            widget.blockSignals(False)
