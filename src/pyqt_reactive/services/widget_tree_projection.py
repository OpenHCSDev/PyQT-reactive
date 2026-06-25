"""Generic QWidget tree projection for window-management integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, TypeAlias, TypeVar

from metaclass_registry import AutoRegisterMeta
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QWidget,
)
from pyqt_reactive.services.widget_tree_projection_config import (
    DEFAULT_WIDGET_TREE_PROJECTION_POLICY,
    WidgetNodeIdentity,
    WidgetPath,
    WidgetTextProjection,
    WidgetTreeProjectionPolicy,
)


TextMethodWidget: TypeAlias = QLineEdit | QAbstractSpinBox
PlainTextMethodWidget: TypeAlias = QTextEdit | QPlainTextEdit
ReadOnlyWidget: TypeAlias = QLineEdit | QAbstractSpinBox | QTextEdit | QPlainTextEdit
WidgetT = TypeVar("WidgetT", bound=QWidget)

ROOT_WIDGET_PATH_ID = "root"
WIDGET_PATH_SEPARATOR = "."


class WidgetProjectionError(RuntimeError):
    """Raised when a QWidget tree cannot be projected through nominal projectors."""


class WidgetActionKind(Enum):
    """Action family exposed for agent/window-manager consumers."""

    BUTTON = "button"
    CHECKABLE = "checkable"
    CHOICE = "choice"
    MENU = "menu"
    SPIN_INPUT = "spin_input"
    TAB_SELECTOR = "tab_selector"
    TEXT_INPUT = "text_input"


@dataclass(frozen=True, slots=True)
class WidgetRect:
    """Integer QRect projection safe to serialize across process boundaries."""

    x: int
    y: int
    width: int
    height: int

    @classmethod
    def from_qrect(cls, rect: QRect) -> "WidgetRect":
        return cls(
            x=rect.x(),
            y=rect.y(),
            width=rect.width(),
            height=rect.height(),
        )


@dataclass(frozen=True, slots=True)
class WidgetProjectionFields:
    """Widget-family-specific fields supplied by one nominal projector."""

    text: str | None = None
    text_truncated: bool = False
    title: str | None = None
    action_kinds: tuple[WidgetActionKind, ...] = ()
    clickable: bool = False
    actionable: bool = False
    checkable: bool | None = None
    checked: bool | None = None
    current_index: int | None = None
    current_text: str | None = None
    item_count: int | None = None

    @classmethod
    def text_action(
        cls,
        *,
        text_projection: WidgetTextProjection,
        action_kind: WidgetActionKind,
        actionable: bool,
    ) -> "WidgetProjectionFields":
        return cls(
            text=text_projection.value,
            text_truncated=text_projection.truncated,
            action_kinds=(action_kind,),
            clickable=actionable,
            actionable=actionable,
        )


@dataclass(frozen=True, slots=True)
class WidgetDescriptor(WidgetNodeIdentity):
    """Serializable description of one QWidget and its projected children."""

    visible: bool
    enabled: bool
    geometry: WidgetRect
    global_geometry: WidgetRect
    tool_tip: str
    status_tip: str
    whats_this: str
    window_title: str
    text: str | None
    text_truncated: bool
    title: str | None
    action_kinds: tuple[WidgetActionKind, ...]
    clickable: bool
    actionable: bool
    checkable: bool | None
    checked: bool | None
    current_index: int | None
    current_text: str | None
    item_count: int | None
    children: tuple["WidgetDescriptor", ...]


@dataclass(frozen=True, slots=True)
class WidgetTreeProjection:
    """Full QWidget tree projection rooted at the requested widget."""

    root: WidgetDescriptor
    widget_count: int
    actionable_count: int


class WidgetDescriptorProjector(ABC, metaclass=AutoRegisterMeta):
    """Nominal projector for one Qt widget class family."""

    __registry_key__ = "widget_type"
    __skip_if_no_key__ = True
    __registry__: ClassVar[dict[type[QWidget], type["WidgetDescriptorProjector"]]] = {}

    widget_type: ClassVar[type[QWidget] | None] = None

    @classmethod
    def registered_projector_types(
        cls,
    ) -> tuple[type["WidgetDescriptorProjector"], ...]:
        return tuple(cls.__registry__.values())

    @classmethod
    def require_widget_type(cls) -> type[QWidget]:
        if cls.widget_type is None:
            raise WidgetProjectionError(
                f"{cls.__name__} must declare widget_type before registration"
            )
        return cls.widget_type

    @abstractmethod
    def project(
        self,
        widget: QWidget,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetProjectionFields:
        """Project widget-family-specific fields."""
        raise NotImplementedError

    def _require_type(
        self,
        widget: QWidget,
        expected_type: type[WidgetT],
    ) -> WidgetT:
        if not isinstance(widget, expected_type):
            raise TypeError(
                f"{type(self).__name__} requires {expected_type.__name__}, "
                f"got {type(widget).__name__}"
            )
        return widget

    def _project_text(
        self,
        text: str,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetProjectionFields:
        projected = policy.project_text(text)
        return WidgetProjectionFields(
            text=projected.value,
            text_truncated=projected.truncated,
        )


class QWidgetDescriptorProjector(WidgetDescriptorProjector):
    """Base QWidget projector used when no more specific Qt family applies."""

    widget_type = QWidget

    def project(
        self,
        widget: QWidget,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetProjectionFields:
        del policy
        self._require_type(widget, QWidget)
        return WidgetProjectionFields()


class QLabelDescriptorProjector(WidgetDescriptorProjector):
    """Project QLabel display text."""

    widget_type = QLabel

    def project(
        self,
        widget: QWidget,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetProjectionFields:
        label = self._require_type(widget, QLabel)
        return self._project_text(label.text(), policy)


class QAbstractButtonDescriptorProjector(WidgetDescriptorProjector):
    """Project button text and current checkable/clickable state."""

    widget_type = QAbstractButton

    def project(
        self,
        widget: QWidget,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetProjectionFields:
        button = self._require_type(widget, QAbstractButton)
        projected = policy.project_text(button.text())
        if button.isCheckable():
            action_kinds = (
                WidgetActionKind.BUTTON,
                WidgetActionKind.CHECKABLE,
            )
            checked = button.isChecked()
            checkable = True
        else:
            action_kinds = (WidgetActionKind.BUTTON,)
            checked = None
            checkable = False

        is_enabled = button.isEnabled()
        return WidgetProjectionFields(
            text=projected.value,
            text_truncated=projected.truncated,
            action_kinds=action_kinds,
            clickable=is_enabled,
            actionable=is_enabled,
            checkable=checkable,
            checked=checked,
        )


class EditableTextDescriptorProjector(WidgetDescriptorProjector):
    """Template projector for editable text-bearing Qt widgets."""

    def project(
        self,
        widget: QWidget,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetProjectionFields:
        return WidgetProjectionFields.text_action(
            text_projection=policy.project_text(self.text_value(widget)),
            action_kind=self.action_kind,
            actionable=widget.isEnabled() and self.is_editable(widget),
        )

    @property
    def action_kind(self) -> WidgetActionKind:
        return WidgetActionKind.TEXT_INPUT

    @abstractmethod
    def text_value(self, widget: QWidget) -> str:
        raise NotImplementedError

    def is_editable(self, widget: QWidget) -> bool:
        return not self.read_only_widget(widget).isReadOnly()

    @abstractmethod
    def read_only_widget(self, widget: QWidget) -> ReadOnlyWidget:
        raise NotImplementedError


class TextMethodEditableDescriptorProjector(EditableTextDescriptorProjector):
    """Template for editable widgets exposing visible content through text()."""

    def text_value(self, widget: QWidget) -> str:
        return self.text_method_widget(widget).text()

    def read_only_widget(self, widget: QWidget) -> ReadOnlyWidget:
        return self.text_method_widget(widget)

    def text_method_widget(self, widget: QWidget) -> TextMethodWidget:
        required_widget_type = self.require_widget_type()
        self._require_type(widget, required_widget_type)
        if isinstance(widget, (QLineEdit, QAbstractSpinBox)):
            return widget
        raise WidgetProjectionError(
            f"{type(self).__name__} must target QLineEdit or QAbstractSpinBox"
        )


class PlainTextMethodEditableDescriptorProjector(EditableTextDescriptorProjector):
    """Template for editable widgets exposing content through toPlainText()."""

    def text_value(self, widget: QWidget) -> str:
        return self.plain_text_method_widget(widget).toPlainText()

    def read_only_widget(self, widget: QWidget) -> ReadOnlyWidget:
        return self.plain_text_method_widget(widget)

    def plain_text_method_widget(self, widget: QWidget) -> PlainTextMethodWidget:
        required_widget_type = self.require_widget_type()
        self._require_type(widget, required_widget_type)
        if isinstance(widget, (QTextEdit, QPlainTextEdit)):
            return widget
        raise WidgetProjectionError(
            f"{type(self).__name__} must target QTextEdit or QPlainTextEdit"
        )


class QLineEditDescriptorProjector(TextMethodEditableDescriptorProjector):
    """Project single-line editable text state."""

    widget_type = QLineEdit


class QTextEditDescriptorProjector(PlainTextMethodEditableDescriptorProjector):
    """Project QTextEdit content through an explicit text bound."""

    widget_type = QTextEdit


class QPlainTextEditDescriptorProjector(PlainTextMethodEditableDescriptorProjector):
    """Project QPlainTextEdit content through an explicit text bound."""

    widget_type = QPlainTextEdit


class QComboBoxDescriptorProjector(WidgetDescriptorProjector):
    """Project combo-box selection state."""

    widget_type = QComboBox

    def project(
        self,
        widget: QWidget,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetProjectionFields:
        del policy
        combo_box = self._require_type(widget, QComboBox)
        is_enabled = combo_box.isEnabled()
        return WidgetProjectionFields(
            action_kinds=(WidgetActionKind.CHOICE,),
            clickable=is_enabled,
            actionable=is_enabled,
            current_index=combo_box.currentIndex(),
            current_text=combo_box.currentText(),
            item_count=combo_box.count(),
        )


class QGroupBoxDescriptorProjector(WidgetDescriptorProjector):
    """Project group-box title and optional checkable state."""

    widget_type = QGroupBox

    def project(
        self,
        widget: QWidget,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetProjectionFields:
        del policy
        group_box = self._require_type(widget, QGroupBox)
        if group_box.isCheckable():
            is_enabled = group_box.isEnabled()
            return WidgetProjectionFields(
                title=group_box.title(),
                action_kinds=(WidgetActionKind.CHECKABLE,),
                clickable=is_enabled,
                actionable=is_enabled,
                checkable=True,
                checked=group_box.isChecked(),
            )

        return WidgetProjectionFields(
            title=group_box.title(),
            checkable=False,
            checked=None,
        )


class QTabWidgetDescriptorProjector(WidgetDescriptorProjector):
    """Project current tab selection state."""

    widget_type = QTabWidget

    def project(
        self,
        widget: QWidget,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetProjectionFields:
        del policy
        tab_widget = self._require_type(widget, QTabWidget)
        current_index = tab_widget.currentIndex()
        current_text = None
        if current_index >= 0:
            current_text = tab_widget.tabText(current_index)

        is_actionable = tab_widget.isEnabled() and tab_widget.count() > 1
        return WidgetProjectionFields(
            action_kinds=(WidgetActionKind.TAB_SELECTOR,),
            clickable=is_actionable,
            actionable=is_actionable,
            current_index=current_index,
            current_text=current_text,
            item_count=tab_widget.count(),
        )


class QStackedWidgetDescriptorProjector(WidgetDescriptorProjector):
    """Project stacked-widget current page state."""

    widget_type = QStackedWidget

    def project(
        self,
        widget: QWidget,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetProjectionFields:
        del policy
        stacked_widget = self._require_type(widget, QStackedWidget)
        return WidgetProjectionFields(
            current_index=stacked_widget.currentIndex(),
            item_count=stacked_widget.count(),
        )


class QAbstractSpinBoxDescriptorProjector(TextMethodEditableDescriptorProjector):
    """Project spin-box visible text and editability."""

    widget_type = QAbstractSpinBox

    @property
    def action_kind(self) -> WidgetActionKind:
        return WidgetActionKind.SPIN_INPUT


class QMenuDescriptorProjector(WidgetDescriptorProjector):
    """Project menu title and clickable state."""

    widget_type = QMenu

    def project(
        self,
        widget: QWidget,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetProjectionFields:
        del policy
        menu = self._require_type(widget, QMenu)
        is_enabled = menu.isEnabled()
        return WidgetProjectionFields(
            title=menu.title(),
            action_kinds=(WidgetActionKind.MENU,),
            clickable=is_enabled,
            actionable=is_enabled,
        )


class WidgetDescriptorProjectorRegistry:
    """Resolve QWidget projectors through the Qt class MRO."""

    def __init__(
        self,
        projector_types: tuple[type[WidgetDescriptorProjector], ...],
    ) -> None:
        projectors_by_type: dict[type[QWidget], WidgetDescriptorProjector] = {}
        for projector_type in projector_types:
            widget_type = projector_type.require_widget_type()
            if widget_type in projectors_by_type:
                raise WidgetProjectionError(
                    f"Duplicate widget projector for {widget_type.__name__}"
                )
            projectors_by_type[widget_type] = projector_type()

        if QWidget not in projectors_by_type:
            raise WidgetProjectionError("QWidgetDescriptorProjector must be registered")

        self._projectors_by_type = projectors_by_type

    @classmethod
    def from_registered_projectors(cls) -> "WidgetDescriptorProjectorRegistry":
        return cls(WidgetDescriptorProjector.registered_projector_types())

    def projector_for(self, widget: QWidget) -> WidgetDescriptorProjector:
        for widget_type in type(widget).mro():
            if widget_type in self._projectors_by_type:
                return self._projectors_by_type[widget_type]

        raise WidgetProjectionError(
            f"No QWidget descriptor projector registered for {type(widget).__name__}"
        )


DEFAULT_WIDGET_DESCRIPTOR_PROJECTOR_REGISTRY = (
    WidgetDescriptorProjectorRegistry.from_registered_projectors()
)


class WidgetTreeProjectionService:
    """Project a QWidget subtree into stable, OpenHCS-agnostic descriptors."""

    @classmethod
    def project(
        cls,
        root: QWidget,
        *,
        registry: WidgetDescriptorProjectorRegistry = (
            DEFAULT_WIDGET_DESCRIPTOR_PROJECTOR_REGISTRY
        ),
        policy: WidgetTreeProjectionPolicy = DEFAULT_WIDGET_TREE_PROJECTION_POLICY,
    ) -> WidgetTreeProjection:
        root_descriptor = cls._project_widget(
            widget=root,
            path=(),
            child_index=None,
            registry=registry,
            policy=policy,
        )
        return WidgetTreeProjection(
            root=root_descriptor,
            widget_count=cls._count_widgets(root_descriptor),
            actionable_count=cls._count_actionable_widgets(root_descriptor),
        )

    @classmethod
    def _project_widget(
        cls,
        *,
        widget: QWidget,
        path: WidgetPath,
        child_index: int | None,
        registry: WidgetDescriptorProjectorRegistry,
        policy: WidgetTreeProjectionPolicy,
    ) -> WidgetDescriptor:
        projector = registry.projector_for(widget)
        fields = projector.project(widget, policy)
        children = cls._project_children(
            widget=widget,
            path=path,
            registry=registry,
            policy=policy,
        )
        return WidgetDescriptor(
            path=path,
            path_id=cls._path_id(path),
            child_index=child_index,
            class_name=type(widget).__name__,
            object_name=widget.objectName(),
            visible=widget.isVisible(),
            enabled=widget.isEnabled(),
            geometry=WidgetRect.from_qrect(widget.geometry()),
            global_geometry=WidgetRect.from_qrect(cls._global_rect(widget)),
            tool_tip=widget.toolTip(),
            status_tip=widget.statusTip(),
            whats_this=widget.whatsThis(),
            window_title=widget.windowTitle(),
            accessible_name=widget.accessibleName(),
            accessible_description=widget.accessibleDescription(),
            text=fields.text,
            text_truncated=fields.text_truncated,
            title=fields.title,
            action_kinds=fields.action_kinds,
            clickable=fields.clickable,
            actionable=fields.actionable,
            checkable=fields.checkable,
            checked=fields.checked,
            current_index=fields.current_index,
            current_text=fields.current_text,
            item_count=fields.item_count,
            children=children,
        )

    @classmethod
    def _project_children(
        cls,
        *,
        widget: QWidget,
        path: WidgetPath,
        registry: WidgetDescriptorProjectorRegistry,
        policy: WidgetTreeProjectionPolicy,
    ) -> tuple[WidgetDescriptor, ...]:
        child_widgets = widget.findChildren(
            QWidget,
            options=Qt.FindChildOption.FindDirectChildrenOnly,
        )
        descriptors: list[WidgetDescriptor] = []
        for child_index, child_widget in enumerate(child_widgets):
            child_path = (*path, child_index)
            descriptors.append(
                cls._project_widget(
                    widget=child_widget,
                    path=child_path,
                    child_index=child_index,
                    registry=registry,
                    policy=policy,
                )
            )
        return tuple(descriptors)

    @staticmethod
    def _path_id(path: WidgetPath) -> str:
        if len(path) == 0:
            return ROOT_WIDGET_PATH_ID
        return WIDGET_PATH_SEPARATOR.join(str(index) for index in path)

    @staticmethod
    def _global_rect(widget: QWidget) -> QRect:
        top_left = widget.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, widget.size())

    @classmethod
    def _count_widgets(cls, descriptor: WidgetDescriptor) -> int:
        count = 1
        for child in descriptor.children:
            count += cls._count_widgets(child)
        return count

    @classmethod
    def _count_actionable_widgets(cls, descriptor: WidgetDescriptor) -> int:
        count = 0
        if descriptor.actionable:
            count += 1
        for child in descriptor.children:
            count += cls._count_actionable_widgets(child)
        return count
