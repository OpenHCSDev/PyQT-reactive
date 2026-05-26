"""Typed list-item hook declarations for manager widgets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from operator import attrgetter
from typing import Any


class ItemIdProjection(ABC):
    """Projects a stable selection id from a manager backing item."""

    @abstractmethod
    def __call__(self, item: Any) -> str:
        ...


@dataclass(frozen=True, slots=True)
class DictItemIdProjection(ItemIdProjection):
    """Project an item id from a mapping key."""

    key: str

    def __call__(self, item: Any) -> str:
        if not isinstance(item, Mapping):
            raise TypeError(
                f"Dict item-id projection expects Mapping, got {type(item).__name__}."
            )
        return str(item[self.key])


@dataclass(frozen=True, slots=True)
class AttributeItemIdProjection(ItemIdProjection):
    """Project an item id from an object attribute path."""

    path: str
    _getter: Callable[[Any], Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_getter", attrgetter(self.path))

    def __call__(self, item: Any) -> str:
        return str(self._getter(item))


@dataclass(frozen=True, slots=True)
class ListItemDataProjection:
    """Bidirectional codec for QListWidgetItem.UserRole payloads."""

    project: Callable[[Any, int], Any]
    resolve_data: Callable[[Any, list[Any]], Any]

    def __call__(self, item: Any, index: int) -> Any:
        return self.project(item, index)

    def resolve(self, data: Any, items: list[Any]) -> Any:
        return self.resolve_data(data, items)


def _project_item(item: Any, index: int) -> Any:
    del index
    return item


def _resolve_item(data: Any, items: list[Any]) -> Any:
    del items
    return data


def _project_index(item: Any, index: int) -> Any:
    del item
    return index


def _resolve_index(data: Any, items: list[Any]) -> Any:
    return items[data] if data is not None and 0 <= data < len(items) else None


ITEM_LIST_DATA_PROJECTION = ListItemDataProjection(
    project=_project_item,
    resolve_data=_resolve_item,
)
INDEX_LIST_DATA_PROJECTION = ListItemDataProjection(
    project=_project_index,
    resolve_data=_resolve_index,
)


@dataclass(frozen=True, slots=True)
class ManagerItemHooks:
    """Typed source for list-item behavior consumed by AbstractManagerWidget."""

    id_projection: ItemIdProjection = field(
        default_factory=lambda: AttributeItemIdProjection("id")
    )
    preserve_selection_pred: Callable[[Any], bool] = lambda _manager: False
    data_projection: ListItemDataProjection = field(
        default_factory=lambda: ITEM_LIST_DATA_PROJECTION
    )

    def item_id(self, item: Any) -> str:
        return self.id_projection(item)

    def should_preserve_selection(self, manager: Any) -> bool:
        return bool(self.preserve_selection_pred(manager))

    def list_item_data_for(self, item: Any, index: int) -> Any:
        return self.data_projection(item, index)

    def item_from_list_data(self, data: Any, items: list[Any]) -> Any:
        return self.data_projection.resolve(data, items)
