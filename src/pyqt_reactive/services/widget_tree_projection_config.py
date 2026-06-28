"""Lightweight widget-tree projection policy shared by window managers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


DEFAULT_MAXIMUM_WIDGET_TEXT_LENGTH = 4096
DEFAULT_MAXIMUM_ITEM_MODEL_NODES = 512
DEFAULT_TEXT_TRUNCATION_SUFFIX = "...<truncated>"
WidgetPath: TypeAlias = tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WidgetTextProjection:
    """Bounded text projection with explicit truncation state."""

    value: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class WidgetNodeIdentity:
    """Stable widget identity fields shared by projector and transport DTOs."""

    path: WidgetPath
    path_id: str
    child_index: int | None
    class_name: str
    object_name: str
    accessible_name: str
    accessible_description: str


@dataclass(frozen=True, kw_only=True)
class WidgetTreeProjectionControls:
    """Projection controls that do not require importing Qt widget classes."""

    maximum_text_length: int = DEFAULT_MAXIMUM_WIDGET_TEXT_LENGTH
    maximum_item_model_nodes: int | None = DEFAULT_MAXIMUM_ITEM_MODEL_NODES
    truncation_suffix: str = DEFAULT_TEXT_TRUNCATION_SUFFIX

    @classmethod
    def default_maximum_text_length(cls) -> int:
        return DEFAULT_MAXIMUM_WIDGET_TEXT_LENGTH

    @classmethod
    def default_maximum_item_model_nodes(cls) -> int:
        return DEFAULT_MAXIMUM_ITEM_MODEL_NODES

    @classmethod
    def default_truncation_suffix(cls) -> str:
        return DEFAULT_TEXT_TRUNCATION_SUFFIX

    def __post_init__(self) -> None:
        if self.maximum_text_length < len(self.truncation_suffix):
            raise ValueError(
                "maximum_text_length must be at least the truncation suffix length"
            )
        if (
            self.maximum_item_model_nodes is not None
            and self.maximum_item_model_nodes < 0
        ):
            raise ValueError("maximum_item_model_nodes must be non-negative or None")

    def project_text(self, text: str) -> WidgetTextProjection:
        if len(text) <= self.maximum_text_length:
            return WidgetTextProjection(value=text, truncated=False)

        prefix_length = self.maximum_text_length - len(self.truncation_suffix)
        return WidgetTextProjection(
            value=f"{text[:prefix_length]}{self.truncation_suffix}",
            truncated=True,
        )

    def as_projection_policy(self) -> "WidgetTreeProjectionPolicy":
        return WidgetTreeProjectionPolicy(
            maximum_text_length=self.maximum_text_length,
            maximum_item_model_nodes=self.maximum_item_model_nodes,
            truncation_suffix=self.truncation_suffix,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class WidgetTreeProjectionPolicy(WidgetTreeProjectionControls):
    """Concrete projection policy used by Qt widget tree projectors."""


DEFAULT_WIDGET_TREE_PROJECTION_POLICY = WidgetTreeProjectionPolicy()
