"""Magicgui-based PyQt6 Widget Creation with OpenHCS Extensions"""

import ast
import dataclasses
import logging
from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from enum import Enum
from pathlib import Path
from typing import ClassVar, Dict, Type, Callable, get_args, get_origin

from PyQt6.QtWidgets import QCheckBox, QLineEdit, QComboBox, QVBoxLayout, QSpinBox, QDoubleSpinBox, QWidget
from PyQt6.QtGui import QIntValidator, QValidator
from magicgui.widgets import Widget as MagicGuiWidget, create_widget
from objectstate import DataclassFieldAccess
from python_introspect import (
    enum_member_type,
    get_enum_from_list,
    is_enum_type,
    is_list_of_enums,
    is_union_type,
    optional_member_type,
    resolve_annotated,
    resolve_optional,
)
from pyqt_reactive.forms.parameter_info_types import ParameterInfo
from pyqt_reactive.forms.parameter_value_contracts import (
    FormObject,
    ParameterValue,
    WidgetValue,
)

from pyqt_reactive.widgets import (
    NoScrollSpinBox, NoScrollDoubleSpinBox, NoScrollComboBox, NoneAwareCheckBox
)
from pyqt_reactive.protocols import (
    ChangeSignalEmitter,
    CurrentValueValidatable,
    KeySequenceEditAdapter,
    PlaceholderStateMixin,
    PlaceholderStateTrackable,
    PyQtWidgetMeta,
    ResolvedValuePreviewSettable,
    ValueGettable,
    ValueSettable,
    WidgetCapability,
    widget_supports_capability,
)
from pyqt_reactive.qt_types import QtKeySequenceText
from pyqt_reactive.protocols.widget_adapters import CheckboxGroupAdapter
from pyqt_reactive.widgets.enhanced_path_widget import EnhancedPathWidget
from pyqt_reactive.theming.color_scheme import ColorScheme as PyQt6ColorScheme
from contextlib import contextmanager

try:
    from pyqt_reactive.core.performance_monitor import timer
except Exception:  # pragma: no cover - optional performance monitoring
    @contextmanager
    def timer(*args, **kwargs):
        yield

logger = logging.getLogger(__name__)
WidgetChangeCallback = Callable[[str, WidgetValue | None], None]
ParameterSignalCallback = Callable[[ParameterValue | None], None]
WidgetSignalCallback = Callable[[WidgetValue | None], None]
WidgetBoundaryTarget = QWidget | MagicGuiWidget
TypeResolvedBoundaryEntry = Callable
TEXT_CHANGE_COMMIT_DEBOUNCE_MS = 120


# ==================== None-Aware Widget Classes ====================
# Defined at top so they can be used throughout this file.

class DebouncedTextSignalMixin:
    """Nominal mixin for line edits that coalesce rapid text changes."""

    def __init__(self, *args, **kwargs):
        self._text_change_emitters = {}
        super().__init__(*args, **kwargs)

    def connect_debounced_text_signal(
        self,
        callback: ParameterSignalCallback,
        value_getter: Callable[[], ParameterValue | None],
        is_committable: Callable[[], bool] | None = None,
    ) -> None:
        self._text_change_emitters[callback] = DebouncedTextChangeEmitter(
            self,
            callback,
            value_getter,
            is_committable=is_committable,
        )

    def disconnect_debounced_text_signal(self, callback: ParameterSignalCallback) -> None:
        emitter = self._text_change_emitters.pop(callback, None)
        if emitter is not None:
            emitter.disconnect()


class NoneAwareTextValueMixin(DebouncedTextSignalMixin):
    """Shared text assignment for widgets that encode None as empty text."""

    def set_value(self, value: ParameterValue | None) -> None:
        if value is None:
            text_value = ""
        else:
            text_value = str(value)
        self.setText(text_value)

    def connect_change_signal(self, callback: ParameterSignalCallback) -> None:
        """Implement ChangeSignalEmitter ABC."""
        self.connect_debounced_text_signal(callback, self.get_value)

    def disconnect_change_signal(self, callback: ParameterSignalCallback) -> None:
        """Implement ChangeSignalEmitter ABC."""
        self.disconnect_debounced_text_signal(callback)


class NoneAwareLineEdit(
    NoneAwareTextValueMixin,
    PlaceholderStateMixin,
    QLineEdit,
    ValueGettable,
    ValueSettable,
    ChangeSignalEmitter,
    metaclass=PyQtWidgetMeta,
):
    """QLineEdit that properly handles None values for lazy dataclass contexts."""

    def get_value(self):
        """Get value, returning None for empty text instead of empty string."""
        text = self.text().strip()
        if text == "":
            return None
        return text


class NoneAwareIntEdit(
    NoneAwareTextValueMixin,
    PlaceholderStateMixin,
    QLineEdit,
    ValueGettable,
    ValueSettable,
    ChangeSignalEmitter,
    metaclass=PyQtWidgetMeta,
):
    """QLineEdit that only allows digits and properly handles None values for integer fields."""

    def __init__(self, parent=None):
        self._committed_value: int | None = None
        super().__init__(parent)
        self.setValidator(QIntValidator())

    def set_value(self, value: ParameterValue | None) -> None:
        """Assign the authoritative value used while edited text is transient."""
        self._committed_value = value
        super().set_value(value)

    def get_value(self):
        """Return the edited integer, or the committed value for invalid text."""
        is_acceptable, value = self._interpreted_text_value()
        if is_acceptable:
            return value
        return self._committed_value

    def connect_change_signal(self, callback: ParameterSignalCallback) -> None:
        """Commit only empty or validator-acceptable integer text."""
        self.connect_debounced_text_signal(
            callback,
            self._commit_current_text,
            is_committable=self._current_text_is_committable,
        )

    def _current_text_is_committable(self) -> bool:
        is_acceptable, _ = self._interpreted_text_value()
        return is_acceptable

    def _commit_current_text(self) -> int | None:
        is_acceptable, value = self._interpreted_text_value()
        if not is_acceptable:
            raise RuntimeError("Cannot commit invalid NoneAwareIntEdit text")
        self._committed_value = value
        return value

    def _interpreted_text_value(self) -> tuple[bool, int | None]:
        text = self.text().strip()
        if text == "":
            return True, None
        validator = self.validator()
        if validator is None:
            raise TypeError("NoneAwareIntEdit requires a QIntValidator before value extraction")
        state, _, _ = validator.validate(text, 0)
        if state != QValidator.State.Acceptable:
            return False, None
        return True, int(text)


class TypedLiteralContainerEdit(
    NoneAwareTextValueMixin,
    PlaceholderStateMixin,
    QLineEdit,
    ValueGettable,
    ValueSettable,
    ChangeSignalEmitter,
    CurrentValueValidatable,
    metaclass=PyQtWidgetMeta,
):
    """Literal editor that preserves a declared container's runtime identity."""

    def __init__(self, container_type: type[list] | type[tuple] | type[dict], parent=None):
        self._container_type = container_type
        self._param_type = container_type
        self._param_name = ""
        super().__init__(parent)
        self.setValidator(TypedLiteralValidator(self._parse_text, self))
        self.setToolTip(self._syntax_help())

    def configure_annotation(self, param_name: str, param_type: Type) -> None:
        """Bind the semantic annotation used by the shared conversion authority."""
        self._param_name = param_name
        self._param_type = param_type

    def set_value(self, value: ParameterValue | None) -> None:
        value = self._project_container(value)
        self._validate_container(value)
        super().set_value(project_literal_edit_value(value))

    def get_value(self) -> ParameterValue | None:
        """Parse the complete editor text or fail before it reaches ObjectState."""
        return self._parse_current_text()

    def validate_current_value(self) -> None:
        """Validate the editor through the same parser used for value extraction."""
        self._parse_current_text()

    def connect_change_signal(self, callback: ParameterSignalCallback) -> None:
        """Emit only complete literals of the declared container kind."""
        self.connect_debounced_text_signal(
            callback,
            self._parse_current_text,
            is_committable=self._current_text_is_committable,
        )

    def _current_text_is_committable(self) -> bool:
        try:
            self._parse_current_text()
        except ValueError:
            return False
        return True

    def _parse_current_text(self) -> ParameterValue | None:
        return self._parse_text(self.text())

    def _parse_text(self, text: str) -> ParameterValue | None:
        text = text.strip()
        if text == "":
            return None
        value = parse_literal_container(text, self._container_type)
        self._validate_container(value)
        from pyqt_reactive.forms.parameter_form_service import ParameterFormService

        return ParameterFormService().convert_value_to_type(
            value,
            self._param_type,
            self._param_name,
        )

    def _validate_container(self, value: ParameterValue | None) -> None:
        if value is None or isinstance(value, self._container_type):
            return
        raise ValueError(
            f"Expected {self._container_type.__name__}, "
            f"got {type(value).__name__}."
        )

    def _project_container(
        self,
        value: ParameterValue | None,
    ) -> ParameterValue | None:
        """Project compatible abstract/default containers into the editor kind."""
        if value is None or isinstance(value, self._container_type):
            return value
        if (
            self._container_type is list
            and isinstance(value, SequenceABC)
            and not isinstance(value, (str, bytes, bytearray))
        ):
            return list(value)
        if (
            self._container_type is tuple
            and isinstance(value, SequenceABC)
            and not isinstance(value, (str, bytes, bytearray))
        ):
            return tuple(value)
        if self._container_type is dict and isinstance(value, MappingABC):
            return dict(value)
        return value

    def _syntax_help(self) -> str:
        example = {
            list: "['value']",
            tuple: "(1, 2)",
            dict: "{'key': 'value'}",
        }[self._container_type]
        return (
            f"Enter a Python {self._container_type.__name__} literal, "
            f"for example {example}."
        )


class LiteralContainerSyntaxError(ValueError):
    """The editor text is not a complete Python literal."""


class LiteralContainerKindError(ValueError):
    """The parsed literal does not match the declared container kind."""


def parse_literal_container(
    text: str,
    container_type: type[list] | type[tuple] | type[dict],
) -> ParameterValue:
    """Parse one complete Python literal for a declared container kind."""
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError) as exc:
        raise LiteralContainerSyntaxError(
            f"Expected a valid {container_type.__name__} literal, got {text!r}."
        ) from exc
    if not isinstance(value, container_type):
        raise LiteralContainerKindError(
            f"Expected {container_type.__name__}, got {type(value).__name__}."
        )
    return value


def project_literal_edit_value(value: ParameterValue | None) -> ParameterValue | None:
    """Project typed values to a literal-safe editable representation."""
    if isinstance(value, Enum):
        return project_literal_edit_value(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [project_literal_edit_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(project_literal_edit_value(item) for item in value)
    if isinstance(value, dict):
        return {
            project_literal_edit_value(key): project_literal_edit_value(item)
            for key, item in value.items()
        }
    return value


class TypedLiteralValidator(QValidator):
    """Qt edit-state projection for an authoritative typed text parser."""

    def __init__(
        self,
        value_parser: Callable[[str], ParameterValue | None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._value_parser = value_parser

    def validate(self, text: str, position: int):
        try:
            self._value_parser(text)
        except LiteralContainerSyntaxError:
            return QValidator.State.Intermediate, text, position
        except ValueError:
            return QValidator.State.Invalid, text, position
        return QValidator.State.Acceptable, text, position


class TypedLiteralUnionEdit(
    NoneAwareTextValueMixin,
    PlaceholderStateMixin,
    QLineEdit,
    ValueGettable,
    ValueSettable,
    ChangeSignalEmitter,
    CurrentValueValidatable,
    metaclass=PyQtWidgetMeta,
):
    """Literal editor for unions whose declared members are safely editable."""

    def __init__(self, param_name: str, param_type: Type, parent=None):
        self._param_name = param_name
        self._param_type = param_type
        members = get_args(param_type)
        self._accepts_none = type(None) in members
        self._accepts_plain_string = str in members
        super().__init__(parent)
        self.setValidator(TypedLiteralValidator(self._parse_text, self))
        member_labels = " | ".join(
            WidgetTypeLabel.render(item) for item in members
        )
        string_help = (
            " Plain unquoted text is accepted as str; quote strings that begin "
            "with a Python literal delimiter."
            if self._accepts_plain_string
            else ""
        )
        self.setToolTip(
            f"Enter a Python literal matching {member_labels}.{string_help}"
        )

    def set_value(self, value: ParameterValue | None) -> None:
        projected = project_literal_edit_value(value)
        super().set_value(projected)

    def get_value(self) -> ParameterValue | None:
        return self._parse_text(self.text())

    def validate_current_value(self) -> None:
        self._parse_text(self.text())

    def connect_change_signal(self, callback: ParameterSignalCallback) -> None:
        self.connect_debounced_text_signal(
            callback,
            self.get_value,
            is_committable=self._current_text_is_committable,
        )

    def _current_text_is_committable(self) -> bool:
        try:
            self.get_value()
        except ValueError:
            return False
        return True

    def _parse_text(self, text: str) -> ParameterValue | None:
        text = text.strip()
        if text == "":
            if self._accepts_none:
                return None
            raise LiteralContainerSyntaxError(
                f"A value matching {self._param_type} is required."
            )
        try:
            value = ast.literal_eval(text)
        except (SyntaxError, ValueError) as exc:
            if (
                not self._accepts_plain_string
                or text.startswith(("[", "{", "(", "'", '"'))
            ):
                raise LiteralContainerSyntaxError(
                    f"Expected a valid literal for {self._param_type}, got {text!r}."
                ) from exc
            value = text

        from pyqt_reactive.forms.parameter_form_service import ParameterFormService

        return ParameterFormService().convert_value_to_type(
            value,
            self._param_type,
            self._param_name,
        )


@dataclasses.dataclass(frozen=True)
class WidgetConfig:
    """Immutable widget configuration constants."""
    NUMERIC_RANGE_MIN: int = -999999
    NUMERIC_RANGE_MAX: int = 999999
    FLOAT_PRECISION: int = 15  # Practical limit for double precision (effectively unlimited)


@dataclasses.dataclass(frozen=True)
class WidgetCreationRequest:
    """Public widget creation request carried through the creation authority."""

    param_name: str
    param_type: Type
    current_value: ParameterValue | None
    widget_id: str
    parameter_info: ParameterInfo | None


@dataclasses.dataclass(frozen=True)
class ResolvedWidgetRequest:
    """Widget request after optional/enum wrappers have been projected."""

    source: WidgetCreationRequest
    resolved_type: Type
    current_value: ParameterValue | None
    accepts_none: bool


class WidgetTypeLabel:
    """Stable type labels for diagnostics and timer names."""

    @staticmethod
    def render(param_type: Type) -> str:
        if isinstance(param_type, type):
            return param_type.__name__
        return str(param_type)


class UnsupportedWidgetTypeError(TypeError):
    """Raised when no typed writable projection exists for an annotation."""


class DirectWidgetFactory:
    """Typed factory for simple widgets that bypass magicgui."""

    def create_int(self, current_value: ParameterValue | None = None) -> NoneAwareIntEdit:
        widget = NoneAwareIntEdit()
        if current_value is not None:
            widget.set_value(current_value)
        return widget

    def create_float(self, current_value: ParameterValue | None = None) -> NoScrollDoubleSpinBox:
        widget = NoScrollDoubleSpinBox()
        widget.setRange(WidgetConfig.NUMERIC_RANGE_MIN, WidgetConfig.NUMERIC_RANGE_MAX)
        widget.setDecimals(WidgetConfig.FLOAT_PRECISION)
        if current_value is not None:
            widget.setValue(float(current_value))
        else:
            widget.clear()
        return widget

    def create_bool(self, current_value: ParameterValue | None = None) -> NoneAwareCheckBox:
        widget = NoneAwareCheckBox()
        if current_value is not None:
            widget.setChecked(bool(current_value))
        return widget

    def create_string(self, current_value: ParameterValue | None = None) -> QLineEdit:
        widget = NoneAwareLineEdit()
        widget.set_value(current_value)
        return widget

    def create_key_sequence(
        self,
        current_value: ParameterValue | None = None,
    ) -> KeySequenceEditAdapter:
        widget = KeySequenceEditAdapter()
        widget.set_value(current_value)
        return widget


DIRECT_WIDGET_FACTORY = DirectWidgetFactory()


class CheckboxGroupWidgetFactory:
    """Factory for List[Enum] checkbox groups."""

    def create(
        self,
        param_name: str,
        param_type: Type,
        current_value: ParameterValue | None,
    ) -> CheckboxGroupAdapter:
        enum_type = get_enum_from_list(param_type)
        widget = CheckboxGroupAdapter()
        widget.setStyleSheet("QGroupBox { background-color: transparent; border: none; }")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        for enum_value in enum_type:
            checkbox = NoneAwareCheckBox()
            checkbox.setText(enum_value.value)
            checkbox.setObjectName(f"{param_name}_{enum_value.value}")
            widget._checkboxes[enum_value] = checkbox
            layout.addWidget(checkbox)

        widget.set_value(current_value)
        return widget


CHECKBOX_GROUP_WIDGET_FACTORY = CheckboxGroupWidgetFactory()


class LiteralContainerWidgetFactory:
    """Creates one type-preserving editor for Python literal containers."""

    container_types: ClassVar[tuple[type[list], type[tuple], type[dict]]] = (
        list,
        tuple,
        dict,
    )
    abstract_container_types: ClassVar[
        dict[type, type[list] | type[tuple] | type[dict]]
    ] = {
        SequenceABC: tuple,
        MappingABC: dict,
    }

    @classmethod
    def container_type_for(
        cls,
        annotation: Type,
    ) -> type[list] | type[tuple] | type[dict] | None:
        """Return the supported container kind declared by ``annotation``."""

        container_type = get_origin(annotation) or annotation
        if container_type in cls.container_types:
            return container_type
        return cls.abstract_container_types.get(container_type)

    @classmethod
    def supports(cls, annotation: Type) -> bool:
        """Return whether this authority can project ``annotation``."""

        return cls.container_type_for(annotation) is not None

    def create(self, request: ResolvedWidgetRequest) -> TypedLiteralContainerEdit | None:
        container_type = self.container_type_for(request.resolved_type)
        if container_type is None:
            return None

        widget = TypedLiteralContainerEdit(container_type)
        widget.configure_annotation(
            request.source.param_name,
            request.resolved_type,
        )
        widget.set_value(request.current_value)
        return widget


LITERAL_CONTAINER_WIDGET_FACTORY = LiteralContainerWidgetFactory()


class LiteralUnionWidgetFactory:
    """Creates typed editors for unions composed only of literal-safe members."""

    scalar_member_types: ClassVar[frozenset[type]] = frozenset(
        {str, int, float, bool}
    )

    def create(self, request: ResolvedWidgetRequest) -> TypedLiteralUnionEdit | None:
        if not is_union_type(request.resolved_type):
            return None
        members = tuple(
            member
            for member in get_args(request.resolved_type)
            if member is not type(None)
        )
        literal_members = tuple(
            member for member in members if self._is_literal_safe(member)
        )
        if not literal_members:
            return None
        if (
            request.current_value is not None
            and not self._value_matches_literal_member(
                request.current_value,
                literal_members,
            )
        ):
            return None

        widget = TypedLiteralUnionEdit(
            request.source.param_name,
            request.resolved_type,
        )
        widget.set_value(request.current_value)
        return widget

    def _is_literal_safe(self, member: Type) -> bool:
        if member in self.scalar_member_types or is_enum_type(member):
            return True
        return LITERAL_CONTAINER_WIDGET_FACTORY.supports(member)

    @staticmethod
    def _value_matches_literal_member(
        value: ParameterValue,
        members: tuple[Type, ...],
    ) -> bool:
        from python_introspect import validate_annotation_value

        for member in members:
            try:
                validate_annotation_value(member, value, path="parameter default")
            except (TypeError, ValueError):
                continue
            return True
        return False


LITERAL_UNION_WIDGET_FACTORY = LiteralUnionWidgetFactory()


class CustomWidgetFactory:
    """Factory for pyqt-reactive widgets that are not owned by magicgui."""

    def create(self, request: ResolvedWidgetRequest) -> QWidget | None:
        if request.resolved_type is not Path:
            return None

        return create_enhanced_path_widget(
            request.source.param_name,
            request.current_value,
            request.source.parameter_info,
        )


CUSTOM_WIDGET_FACTORY = CustomWidgetFactory()


class MagicGuiValueBoundary:
    """Formal boundary defaults required by magicgui widget construction."""

    @staticmethod
    def project(resolved_type: Type, extracted_value: ParameterValue | None) -> ParameterValue | None:
        if extracted_value is not None:
            return extracted_value

        if resolved_type == int:
            return 0
        if resolved_type == float:
            return 0.0
        if resolved_type == bool:
            return False
        return None


class MagicGuiWidgetFactory:
    """Magicgui creation plus fail-loud projection back to PyQt widgets."""

    def create(self, request: ResolvedWidgetRequest) -> QWidget:
        try:
            with timer("            prepare magicgui value", threshold_ms=0.1):
                magicgui_value = MagicGuiValueBoundary.project(
                    request.resolved_type,
                    request.current_value,
                )

            label = WidgetTypeLabel.render(request.resolved_type)
            with timer(
                f"            magicgui.create_widget({request.source.param_name}, {label})",
                threshold_ms=0.0,
            ):
                created_widget = create_widget(
                    annotation=request.resolved_type,
                    value=magicgui_value,
                )

            return self._project_widget(request, created_widget)
        except Exception as exc:
            raise UnsupportedWidgetTypeError(
                "No typed writable widget projection exists for "
                f"parameter {request.source.param_name!r} with annotation "
                f"{WidgetTypeLabel.render(request.resolved_type)!r}."
            ) from exc

    def _project_widget(
        self,
        request: ResolvedWidgetRequest,
        created_widget: QWidget | MagicGuiWidget,
    ) -> QWidget:
        with timer("            check magicgui result", threshold_ms=0.1):
            native_widget = self._native_widget(created_widget)
            if isinstance(native_widget, QWidget) and type(native_widget) is QWidget:
                raise UnsupportedWidgetTypeError(
                    "magicgui returned an untyped QWidget for "
                    f"parameter {request.source.param_name!r} with annotation "
                    f"{WidgetTypeLabel.render(request.resolved_type)!r}."
                )

            if type(created_widget) is QWidget:
                raise UnsupportedWidgetTypeError(
                    "magicgui returned an untyped QWidget for "
                    f"parameter {request.source.param_name!r} with annotation "
                    f"{WidgetTypeLabel.render(request.resolved_type)!r}."
                )

            if request.current_value is None and native_widget is not None:
                self._clear_magicgui_none_preview(native_widget, request.resolved_type)

            if native_widget is not None:
                native_widget.setProperty("magicgui_widget", created_widget)
                return native_widget

            if isinstance(created_widget, QWidget):
                return created_widget

            raise TypeError(
                f"magicgui produced {type(created_widget).__name__} without a native QWidget"
            )

    @staticmethod
    def _native_widget(created_widget: QWidget | MagicGuiWidget) -> QWidget | None:
        if isinstance(created_widget, MagicGuiWidget):
            native = created_widget.native
            if isinstance(native, QWidget):
                return native
        return None

    @staticmethod
    def _clear_magicgui_none_preview(native_widget: QWidget, resolved_type: Type) -> None:
        if isinstance(native_widget, QLineEdit):
            native_widget.setText("")
            return
        if isinstance(native_widget, QCheckBox) and resolved_type == bool:
            native_widget.setChecked(False)


MAGICGUI_WIDGET_FACTORY = MagicGuiWidgetFactory()


class PyQt6WidgetCreationAuthority:
    """Nominal authority for choosing the widget creation path."""

    direct_factories: ClassVar[Dict[Type, Callable[[ParameterValue | None], QWidget]]] = {
        int: DIRECT_WIDGET_FACTORY.create_int,
        float: DIRECT_WIDGET_FACTORY.create_float,
        bool: DIRECT_WIDGET_FACTORY.create_bool,
        str: DIRECT_WIDGET_FACTORY.create_string,
        QtKeySequenceText: DIRECT_WIDGET_FACTORY.create_key_sequence,
    }

    def create(self, request: WidgetCreationRequest) -> QWidget:
        with timer("            resolve_optional", threshold_ms=0.1):
            resolved = self._resolve_request(request)

        if is_list_of_enums(resolved.resolved_type):
            with timer("            create checkbox group", threshold_ms=0.5):
                return CHECKBOX_GROUP_WIDGET_FACTORY.create(
                    request.param_name,
                    resolved.resolved_type,
                    resolved.current_value,
                )

        if is_enum_type(resolved.resolved_type):
            with timer("            create enum widget", threshold_ms=0.5):
                return create_enum_widget_unified(
                    resolved.resolved_type,
                    resolved.current_value,
                    accepts_none=resolved.accepts_none,
                )

        direct_factory = self.direct_factories.get(resolved.resolved_type)
        if direct_factory is not None:
            label = WidgetTypeLabel.render(resolved.resolved_type)
            with timer(f"            create {label} widget (fast path)", threshold_ms=0.5):
                return direct_factory(resolved.current_value)

        literal_container_widget = LITERAL_CONTAINER_WIDGET_FACTORY.create(resolved)
        if literal_container_widget is not None:
            return literal_container_widget

        literal_union_widget = LITERAL_UNION_WIDGET_FACTORY.create(resolved)
        if literal_union_widget is not None:
            return literal_union_widget

        with timer("            registry lookup", threshold_ms=0.1):
            custom_widget = CUSTOM_WIDGET_FACTORY.create(resolved)
        if custom_widget is not None:
            return custom_widget

        return MAGICGUI_WIDGET_FACTORY.create(resolved)

    def _resolve_request(self, request: WidgetCreationRequest) -> ResolvedWidgetRequest:
        resolved_type = request.param_type
        accepts_none = False
        while resolved_type not in self.direct_factories:
            owned_type = resolve_annotated(resolved_type)
            if owned_type != resolved_type:
                resolved_type = owned_type
                continue
            if optional_member_type(resolved_type) is not None:
                accepts_none = True
            required_type = resolve_optional(resolved_type)
            if required_type == resolved_type:
                break
            resolved_type = required_type

        enum_type = enum_member_type(resolved_type)
        current_value = request.current_value
        if enum_type is not None:
            resolved_type = enum_type
            current_value = self._extract_single_enum_value(current_value)

        return ResolvedWidgetRequest(
            source=request,
            resolved_type=resolved_type,
            current_value=current_value,
            accepts_none=accepts_none,
        )

    @staticmethod
    def _extract_single_enum_value(value: ParameterValue | None) -> ParameterValue | None:
        if not isinstance(value, list):
            return value
        if len(value) != 1:
            return value
        first_value = value[0]
        if isinstance(first_value, Enum):
            return first_value
        return value


PYQT6_WIDGET_CREATION = PyQt6WidgetCreationAuthority()


def create_enhanced_path_widget(param_name: str = "", current_value: ParameterValue | None = None, parameter_info: ParameterInfo | None = None) -> EnhancedPathWidget:
    """Factory function for OpenHCS enhanced path widgets."""
    return EnhancedPathWidget(param_name, current_value, parameter_info, PyQt6ColorScheme())


def _create_none_aware_int_widget():
    """Factory function for NoneAwareIntEdit widgets."""
    return NoneAwareIntEdit()


def _create_none_aware_checkbox():
    """Factory function for NoneAwareCheckBox widgets."""
    return NoneAwareCheckBox()


def convert_widget_value_to_type(value: WidgetValue | None, param_type: Type) -> ParameterValue | None:
    """
    PyQt-specific type conversions for widget values.

    Handles conversions that are specific to how PyQt widgets represent values
    (for example, Path widgets return strings).

    Args:
        value: The raw value from the widget
        param_type: The target parameter type

    Returns:
        The converted value ready for the service layer
    """
    if param_type is Path and isinstance(value, str):
        if value == "":
            return None
        return Path(value)

    return value


def create_enum_widget_unified(
    enum_type: Type,
    current_value: ParameterValue | None,
    *,
    accepts_none: bool = False,
) -> QComboBox:
    """Unified enum widget creator with consistent display text."""
    from pyqt_reactive.forms.ui_utils import format_enum_display

    widget = NoScrollComboBox()

    if accepts_none:
        widget.addItem("Default", None)

    # Add all enum items
    for enum_value in enum_type:
        display_text = format_enum_display(enum_value)
        widget.addItem(display_text, enum_value)

    # Set current selection
    enum_value = coerce_enum_widget_value(enum_type, current_value)
    if enum_value is not None:
        _select_combobox_data(widget, enum_value)

    return widget


def coerce_enum_widget_value(enum_type: Type, value: ParameterValue | None) -> Enum | None:
    """Coerce enum-compatible UI values through the enum declaration itself."""
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        return None
    for enum_value in enum_type:
        if value in (enum_value.value, enum_value.name, str(enum_value)):
            return enum_value
    return None


def _select_combobox_data(widget: QComboBox, value: ParameterValue) -> None:
    """Select the first combobox entry whose item data matches value."""
    for index in range(widget.count()):
        if widget.itemData(index) == value:
            widget.setCurrentIndex(index)
            return


def create_pyqt6_widget(
    param_name: str,
    param_type: Type,
    current_value: ParameterValue | None,
    widget_id: str,
    parameter_info: ParameterInfo | None = None,
) -> QWidget:
    """Create a PyQt6 widget using the functional widget strategy."""
    return PYQT6_WIDGET_CREATION.create(
        WidgetCreationRequest(
            param_name=param_name,
            param_type=param_type,
            current_value=current_value,
            widget_id=widget_id,
            parameter_info=parameter_info,
        )
    )


class PlaceholderConfig:
    """Declarative placeholder configuration."""
    PLACEHOLDER_PREFIX = "Pipeline default: "
    INTERACTION_HINTS = {
        'checkbox': 'click to set your own value',
        'combobox': 'select to set your own value'
    }

    @classmethod
    def text_color_name(cls) -> str:
        return "#888888"

    @classmethod
    def text_style(cls, *, include_opacity: bool = True) -> str:
        opacity = " opacity: 0.7;" if include_opacity else ""
        return (
            f"color: {cls.text_color_name()} !important; "
            f"font-style: italic !important;{opacity}"
        )


def _placeholder_state(widget: QWidget) -> PlaceholderStateTrackable:
    """Return the nominal placeholder-state contract for a widget."""
    has_capability = widget_supports_capability(widget, WidgetCapability.PLACEHOLDER_STATE)
    if not isinstance(widget, PlaceholderStateTrackable):
        raise TypeError(
            f"Widget {type(widget).__name__} must implement PlaceholderStateTrackable "
            "to participate in placeholder rendering"
        )
    if not has_capability:
        raise TypeError(
            f"Widget {type(widget).__name__} implements PlaceholderStateTrackable "
            "but does not declare the placeholder-state capability tag"
        )
    return widget


def _supports_placeholder_state(widget: QWidget) -> bool:
    """Return whether the widget nominally exposes placeholder-state operations."""
    return (
        widget_supports_capability(widget, WidgetCapability.PLACEHOLDER_STATE)
        and isinstance(widget, PlaceholderStateTrackable)
    )


def _get_cached_placeholder_text(widget: QWidget) -> str | None:
    """Return cached placeholder text from the widget's nominal state contract."""
    return _placeholder_state(widget).cached_placeholder_text()


def _set_cached_placeholder_text(widget: QWidget, placeholder_text: str) -> None:
    """Store cached placeholder text on the widget's nominal state contract."""
    _placeholder_state(widget).set_cached_placeholder_text(placeholder_text)


def _get_cached_placeholder_resolved_value(widget: QWidget):
    """Return cached resolved placeholder value from the widget state contract."""
    return _placeholder_state(widget).cached_placeholder_resolved_value()


def _set_cached_placeholder_resolved_value(widget: QWidget, value) -> None:
    """Store cached resolved placeholder value on the widget state contract."""
    _placeholder_state(widget).set_cached_placeholder_resolved_value(value)


def _clear_cached_placeholder_text(widget: QWidget) -> None:
    """Clear cached placeholder text on the widget's nominal state contract."""
    _placeholder_state(widget).clear_placeholder_cache()


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
            style = PlaceholderConfig.text_style()

        widget.setStyleSheet(style)
        widget.setToolTip(f"{placeholder_text} ({interaction_hint})")
        _placeholder_state(widget).mark_placeholder_state()

    def apply_lineedit(self, widget: QLineEdit, text: str) -> None:
        """Apply placeholder to line edit with proper state tracking."""
        was_blocked = widget.blockSignals(True)
        try:
            widget.clear()
            widget.setPlaceholderText(text)
        finally:
            widget.blockSignals(was_blocked)
        _placeholder_state(widget).mark_placeholder_state()
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
            _placeholder_state(widget).mark_placeholder_state()
            widget.update()
        except Exception:
            widget.setToolTip(placeholder_text)

    def apply_path_widget(self, widget: EnhancedPathWidget, placeholder_text: str) -> None:
        """Apply placeholder to Path widget by targeting the inner QLineEdit."""
        was_blocked = widget.path_input.blockSignals(True)
        try:
            widget.path_input.clear()
            widget.path_input.setPlaceholderText(placeholder_text)
        finally:
            widget.path_input.blockSignals(was_blocked)
        _placeholder_state(widget).mark_placeholder_state()
        widget.path_input.setToolTip(placeholder_text)

    def apply_combobox(self, widget: QComboBox, placeholder_text: str) -> None:
        """Apply placeholder to combobox while preserving None as no concrete selection."""
        try:
            default_value = self.extract_default_value(placeholder_text)
            matching_index = _find_matching_combobox_index(widget, default_value)
            placeholder_display = _combobox_placeholder_display(
                widget,
                matching_index,
                default_value,
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
            _placeholder_state(widget).mark_placeholder_state()
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


def _find_matching_combobox_index(widget: QComboBox, target_value: str) -> int:
    """Return the matching item index, or -1 for an explicit cache miss."""
    for index in range(widget.count()):
        if _item_matches_value(widget, index, target_value):
            return index
    return -1


def _combobox_placeholder_display(
    widget: QComboBox,
    matching_index: int,
    default_value: str,
) -> str:
    """Project a combobox placeholder label from a match or cache miss."""
    if matching_index >= 0:
        return widget.itemText(matching_index)
    return default_value


def _tooltip_without_interaction_hints(current_tooltip: str) -> str:
    """Remove any known placeholder interaction suffix from a tooltip."""
    for hint in PlaceholderConfig.INTERACTION_HINTS.values():
        suffix = f" ({hint})"
        if suffix in current_tooltip:
            return current_tooltip.replace(suffix, "")
    return current_tooltip


@dataclasses.dataclass(frozen=True)
class WidgetTypeEntryResolver:
    """MRO-aware lookup for raw widget boundary entries."""

    mapping: Dict[Type, TypeResolvedBoundaryEntry]

    def entry_for(self, widget: WidgetBoundaryTarget) -> TypeResolvedBoundaryEntry | None:
        for widget_type in type(widget).__mro__:
            entry = self.mapping.get(widget_type)
            if entry is not None:
                return entry
        return None


# Declarative widget-to-strategy mapping
WIDGET_PLACEHOLDER_STRATEGIES: Dict[Type, Callable[[QWidget, str], None]] = {
    QCheckBox: PLACEHOLDER_RENDERER.apply_checkbox,
    QComboBox: PLACEHOLDER_RENDERER.apply_combobox,
    QSpinBox: PLACEHOLDER_RENDERER.apply_spinbox,
    QDoubleSpinBox: PLACEHOLDER_RENDERER.apply_spinbox,
    QLineEdit: PLACEHOLDER_RENDERER.apply_lineedit,
    EnhancedPathWidget: PLACEHOLDER_RENDERER.apply_path_widget,
}
WIDGET_PLACEHOLDER_RESOLVER = WidgetTypeEntryResolver(
    WIDGET_PLACEHOLDER_STRATEGIES
)


class MagicguiWrapperFamilyAuthority:
    """Projects magicgui wrapper identity from native or wrapper widgets."""

    def get(self, widget: WidgetBoundaryTarget) -> MagicGuiWidget | None:
        if isinstance(widget, QWidget):
            wrapper = widget.property("magicgui_widget")
            if isinstance(wrapper, MagicGuiWidget):
                return wrapper
        if isinstance(widget, MagicGuiWidget):
            return widget
        return None


MAGICGUI_WRAPPER_FAMILY = MagicguiWrapperFamilyAuthority()


class DebouncedTextChangeEmitter:
    """Coalesce rapid textChanged signals into one semantic value commit."""

    def __init__(
        self,
        widget: QLineEdit,
        callback: WidgetSignalCallback,
        value_getter: Callable[[], WidgetValue | None],
        delay_ms: int = TEXT_CHANGE_COMMIT_DEBOUNCE_MS,
        is_committable: Callable[[], bool] | None = None,
    ) -> None:
        from PyQt6.QtCore import QTimer

        self._widget = widget
        self._callback = callback
        self._value_getter = value_getter
        self._is_committable = is_committable
        self._timer = QTimer(widget)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self.emit)

        widget.textChanged.connect(self.schedule)
        widget.editingFinished.connect(self.flush)

    def schedule(self, *_args) -> None:
        self._timer.start()

    def flush(self) -> None:
        if not self._timer.isActive():
            return
        self._timer.stop()
        self.emit()

    def emit(self) -> None:
        if self._is_committable is not None and not self._is_committable():
            return
        self._callback(self._value_getter())

    def disconnect(self) -> None:
        self._timer.stop()
        try:
            self._widget.textChanged.disconnect(self.schedule)
        except TypeError:
            pass
        try:
            self._widget.editingFinished.disconnect(self.flush)
        except TypeError:
            pass
        try:
            self._timer.timeout.disconnect(self.emit)
        except TypeError:
            pass


def _connect_raw_checkbox(widget: QCheckBox, callback: WidgetSignalCallback) -> None:
    widget.stateChanged.connect(lambda: callback(widget.isChecked()))


def _connect_raw_lineedit(widget: QLineEdit, callback: WidgetSignalCallback) -> None:
    def emit_text(value: str) -> None:
        if isinstance(widget, ValueGettable):
            callback(widget.get_value())
            return
        callback(value)

    widget.textChanged.connect(emit_text)


def _connect_raw_spinbox(widget: QSpinBox | QDoubleSpinBox, callback: WidgetSignalCallback) -> None:
    widget.valueChanged.connect(callback)


def _connect_raw_combobox(widget: QComboBox, callback: WidgetSignalCallback) -> None:
    widget.currentIndexChanged.connect(lambda: callback(widget.currentData()))


RawWidgetSignalConnector = Callable[[QWidget, WidgetSignalCallback], None]

RAW_WIDGET_SIGNAL_CONNECTORS: Dict[Type, RawWidgetSignalConnector] = {
    QCheckBox: _connect_raw_checkbox,
    QLineEdit: _connect_raw_lineedit,
    QSpinBox: _connect_raw_spinbox,
    QDoubleSpinBox: _connect_raw_spinbox,
    QComboBox: _connect_raw_combobox,
}
RAW_WIDGET_SIGNAL_RESOLVER = WidgetTypeEntryResolver(RAW_WIDGET_SIGNAL_CONNECTORS)


class WidgetSignalConnectionAuthority:
    """Boundary authority for connecting widget change signals."""

    def connect(
        self,
        widget: WidgetBoundaryTarget,
        param_name: str,
        callback: WidgetChangeCallback,
    ) -> None:
        magicgui_widget = MAGICGUI_WRAPPER_FAMILY.get(widget)
        if magicgui_widget is not None:
            magicgui_widget.changed.connect(
                self._wrapped_callback(widget, param_name, callback, lambda: magicgui_widget.value)
            )
            return

        if isinstance(widget, ChangeSignalEmitter):
            widget.connect_change_signal(
                lambda value: self._emit_value(widget, param_name, callback, value)
            )
            return

        connector = RAW_WIDGET_SIGNAL_RESOLVER.entry_for(widget)
        if connector is not None:
            connector(
                widget,
                lambda value: self._emit_value(widget, param_name, callback, value),
            )
            return

        raise ValueError(f"Widget {type(widget).__name__} has no supported change signal")

    def _wrapped_callback(
        self,
        widget: WidgetBoundaryTarget,
        param_name: str,
        callback: WidgetChangeCallback,
        value_getter: Callable[[], WidgetValue | None],
    ) -> Callable[[], None]:
        def wrapped() -> None:
            self._emit_value(widget, param_name, callback, value_getter())

        return wrapped

    @staticmethod
    def _emit_value(
        widget: WidgetBoundaryTarget,
        param_name: str,
        callback: WidgetChangeCallback,
        value: WidgetValue | None,
    ) -> None:
        if isinstance(widget, QWidget):
            PyQt6WidgetEnhancer._clear_placeholder_state(widget)
        callback(param_name, value)


def _set_raw_checkbox(widget: QCheckBox, value: ParameterValue | None) -> None:
    widget.setChecked(bool(value))


def _set_raw_spinbox(widget: QSpinBox, value: ParameterValue | None) -> None:
    if value is None:
        widget_value = 0
    else:
        widget_value = int(value)
    widget.setValue(widget_value)


def _set_raw_double_spinbox(widget: QDoubleSpinBox, value: ParameterValue | None) -> None:
    if value is None:
        widget_value = 0.0
    else:
        widget_value = float(value)
    widget.setValue(widget_value)


def _set_raw_combobox(widget: QComboBox, value: ParameterValue | None) -> None:
    _select_combobox_data(widget, value)


def _set_raw_lineedit(widget: QLineEdit, value: ParameterValue | None) -> None:
    if value is None:
        widget_value = ""
    else:
        widget_value = str(value)
    widget.setText(widget_value)


def _set_magicgui_widget(widget: MagicGuiWidget, value: ParameterValue | None) -> None:
    widget.value = value


RawWidgetValueSetter = Callable[[WidgetBoundaryTarget, ParameterValue | None], None]

RAW_WIDGET_VALUE_SETTERS: Dict[Type, RawWidgetValueSetter] = {
    QCheckBox: _set_raw_checkbox,
    QSpinBox: _set_raw_spinbox,
    QDoubleSpinBox: _set_raw_double_spinbox,
    QComboBox: _set_raw_combobox,
    QLineEdit: _set_raw_lineedit,
    MagicGuiWidget: _set_magicgui_widget,
}
RAW_WIDGET_VALUE_SETTER_RESOLVER = WidgetTypeEntryResolver(RAW_WIDGET_VALUE_SETTERS)


class WidgetValueAssignmentAuthority:
    """Boundary authority for assigning values to widgets."""

    def assign(self, widget: WidgetBoundaryTarget, value: ParameterValue | None) -> None:
        if isinstance(widget, ValueSettable):
            widget.set_value(value)
            return

        setter = RAW_WIDGET_VALUE_SETTER_RESOLVER.entry_for(widget)
        if setter is not None:
            setter(widget, value)
            return

        raise TypeError(f"Widget {type(widget).__name__} has no supported value assignment")


WIDGET_SIGNAL_CONNECTION = WidgetSignalConnectionAuthority()
WIDGET_VALUE_ASSIGNMENT = WidgetValueAssignmentAuthority()


@dataclasses.dataclass(frozen=True)
class PyQt6WidgetEnhancer:
    """Widget enhancement using functional dispatch patterns."""

    @staticmethod
    def supports_placeholder(widget: QWidget) -> bool:
        """Return whether the registered widget authority can render a placeholder."""
        return (
            isinstance(widget, ResolvedValuePreviewSettable)
            or WIDGET_PLACEHOLDER_RESOLVER.entry_for(widget) is not None
        )

    @staticmethod
    def has_placeholder_state(widget: QWidget) -> bool:
        """Return whether the widget has placeholder chrome or cached placeholder data."""
        return _supports_placeholder_state(widget) and widget.has_placeholder_state()

    @staticmethod
    def apply_placeholder_text(widget: QWidget, placeholder_text: str) -> None:
        """Apply placeholder using declarative widget-strategy mapping."""
        # PERFORMANCE OPTIMIZATION: Skip if placeholder text is unchanged
        # This avoids redundant widget updates during sibling refresh cascades
        if not isinstance(widget, QWidget):
            raise TypeError(f"Placeholder support requires QWidget, got {type(widget).__name__}")

        if isinstance(widget, ResolvedValuePreviewSettable):
            raise TypeError(
                f"Widget {type(widget).__name__} owns typed resolved previews; "
                "use apply_placeholder_with_value."
            )

        cached_placeholder = _get_cached_placeholder_text(widget)
        if cached_placeholder == placeholder_text:
            return  # No change needed

        widget_strategy = WIDGET_PLACEHOLDER_RESOLVER.entry_for(widget)
        if widget_strategy is not None:
            widget_strategy(widget, placeholder_text)
            _set_cached_placeholder_text(widget, placeholder_text)
            return

        raise TypeError(
            f"Widget {type(widget).__name__} has no registered placeholder strategy"
        )

    @staticmethod
    def apply_placeholder_with_value(widget: QWidget, resolved_value: ParameterValue | None, placeholder_text: str) -> None:
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

        if isinstance(widget, ResolvedValuePreviewSettable):
            if (
                _get_cached_placeholder_text(widget) == placeholder_text
                and _get_cached_placeholder_resolved_value(widget) == resolved_value
            ):
                return
            widget.set_resolved_value_preview(resolved_value)
            _set_cached_placeholder_text(widget, placeholder_text)
            _set_cached_placeholder_resolved_value(widget, resolved_value)
            return

        cached_placeholder = _get_cached_placeholder_text(widget)
        if cached_placeholder == placeholder_text:
            return  # No change needed

        # For other widgets, fall back to text-based placeholder
        PyQt6WidgetEnhancer.apply_placeholder_text(widget, placeholder_text)

    @staticmethod
    def apply_global_config_placeholder(widget: QWidget, field_name: str, global_config: FormObject) -> None:
        """
        Apply placeholder to standalone widget using global config.

        This method allows applying placeholders to widgets that are not part of
        a dataclass form by directly using the global configuration.

        Args:
            widget: The widget to apply placeholder to
            field_name: Name of the field in the global config
            global_config: Global config instance
        """
        try:
            if not dataclasses.is_dataclass(global_config):
                return

            if DataclassFieldAccess.has_field(global_config, field_name):
                field_value = DataclassFieldAccess.raw_value(global_config, field_name)

                # Format the placeholder text appropriately for different types
                if isinstance(field_value, Enum):
                    from pyqt_reactive.forms.ui_utils import format_enum_placeholder
                    placeholder_text = format_enum_placeholder(field_value)
                else:
                    placeholder_text = f"Pipeline default: {field_value}"

                if isinstance(widget, ResolvedValuePreviewSettable):
                    PyQt6WidgetEnhancer.apply_placeholder_with_value(
                        widget,
                        field_value,
                        placeholder_text,
                    )
                else:
                    PyQt6WidgetEnhancer.apply_placeholder_text(widget, placeholder_text)
        except Exception:
            # Silently fail if placeholder can't be applied
            pass

    @staticmethod
    def connect_change_signal(widget: QWidget | MagicGuiWidget, param_name: str, callback: WidgetChangeCallback) -> None:
        """Connect signal with placeholder state management."""
        WIDGET_SIGNAL_CONNECTION.connect(widget, param_name, callback)

    @staticmethod
    def _clear_placeholder_state(widget: QWidget) -> None:
        """Clear placeholder state using functional approach."""
        # Handle checkbox groups by clearing each checkbox's placeholder state
        if isinstance(widget, CheckboxGroupAdapter):
            for checkbox in widget.checkbox_widgets():
                # CRITICAL FIX: Always clear cached placeholder text first, even if
                # the checkbox is not in placeholder state. This ensures resetting to
                # None will properly reapply the placeholder (not skip due to cache hit).
                checkbox_state = _placeholder_state(checkbox)
                checkbox_state.clear_placeholder_cache()
                if checkbox_state.has_placeholder_state():
                    checkbox.setStyleSheet("")
                    checkbox_state.clear_placeholder_state()
                    checkbox.convert_placeholder_to_concrete()
                    # Clean checkbox tooltip
                    current_tooltip = checkbox.toolTip()
                    cleaned_tooltip = _tooltip_without_interaction_hints(current_tooltip)
                    checkbox.setToolTip(cleaned_tooltip)
            # Clear group widget's placeholder state and cache
            widget.clear_placeholder_state()
            widget.setToolTip("")
            widget.clear_placeholder_cache()
            return

        # CRITICAL FIX: Always clear cached placeholder text when exiting placeholder state.
        # This ensures that resetting to None will properly reapply the placeholder
        # (not skip due to cache hit). The cache must be cleared even if the widget
        # is already in non-placeholder state (e.g., user clicked checkbox).
        placeholder_state = _placeholder_state(widget)
        placeholder_state.clear_placeholder_cache()

        if not placeholder_state.has_placeholder_state():
            return

        widget.setStyleSheet("")
        placeholder_state.clear_placeholder_state()

        # Clean tooltip using functional pattern
        current_tooltip = widget.toolTip()
        cleaned_tooltip = _tooltip_without_interaction_hints(current_tooltip)
        widget.setToolTip(cleaned_tooltip)

    @staticmethod
    def _get_magicgui_wrapper(widget: QWidget | MagicGuiWidget) -> MagicGuiWidget | None:
        """Get magicgui wrapper if widget was created by magicgui."""
        return MAGICGUI_WRAPPER_FAMILY.get(widget)

    @staticmethod
    def set_widget_value(widget: QWidget | MagicGuiWidget, value: ParameterValue | None) -> None:
        """
        Set widget value without triggering signals.

        Args:
            widget: Widget to update
            value: New value
        """
        # Temporarily block signals to avoid recursion
        widget.blockSignals(True)

        try:
            WIDGET_VALUE_ASSIGNMENT.assign(widget, value)
        finally:
            widget.blockSignals(False)
