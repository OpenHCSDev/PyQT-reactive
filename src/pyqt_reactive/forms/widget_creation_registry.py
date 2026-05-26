"""Shared annotation helpers for widget creation strategies."""

from types import UnionType
from typing import Type, get_origin, get_args, Union
from enum import Enum


def is_union_type(param_type: Type) -> bool:
    """Check whether a type annotation is a typing or PEP 604 union."""
    return get_origin(param_type) in (Union, UnionType)


def resolve_optional(param_type: Type) -> Type:
    """Resolve Optional[T] to T."""
    if is_union_type(param_type):
        args = get_args(param_type)
        if len(args) == 2 and type(None) in args:
            return next(arg for arg in args if arg is not type(None))
    return param_type


def is_enum(param_type: Type) -> bool:
    """Check if type is an Enum."""
    return isinstance(param_type, type) and issubclass(param_type, Enum)


def enum_member_type(param_type: Type) -> Type | None:
    """Return the enum member from a union annotation, if one is present."""
    if is_enum(param_type):
        return param_type
    if not is_union_type(param_type):
        return None
    enum_args = [arg for arg in get_args(param_type) if is_enum(arg)]
    if len(enum_args) == 1:
        return enum_args[0]
    return None


def is_list_of_enums(param_type: Type) -> bool:
    """Check if type is List[Enum]."""
    return (get_origin(param_type) is list and
            get_args(param_type) and
            is_enum(get_args(param_type)[0]))


def get_enum_from_list(param_type: Type) -> Type:
    """Extract enum type from List[Enum]."""
    return get_args(param_type)[0]

