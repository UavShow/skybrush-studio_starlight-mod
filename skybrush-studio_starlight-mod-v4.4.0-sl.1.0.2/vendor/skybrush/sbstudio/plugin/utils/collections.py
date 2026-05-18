

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from inspect import signature
from itertools import count
from operator import attrgetter
from typing import (
    TYPE_CHECKING,
    Any,
    TypeVar,
    overload,
)

import bpy
from bpy.types import Collection, Object

from .identifiers import create_internal_id

if TYPE_CHECKING:
    from bpy.types import ID, bpy_prop_collection

__all__ = (
    "create_object_in_collection",
    "filter_collection",
    "find_empty_slot_in",
    "get_object_in_collection",
    "pick_unique_name",
    "sort_collection",
)

T = TypeVar("T", bound="ID")
D = TypeVar("D")


def create_object_in_collection(
    collection: bpy_prop_collection[T],
    name: str,
    factory: Callable[[], T] | None = None,
    remover: Callable[[T], None]
    | Callable[[T, bpy_prop_collection[T]], None]
    | None = None,
    internal: bool = False,
    *args,
    **kwds,
) -> T:
    
    existing = get_object_in_collection(
        collection, name, default=None, internal=internal
    )
    if existing is not None:
        if callable(remover):
            sig = signature(remover)
            if len(sig.parameters) > 1:
                remover(existing, collection)  
            else:
                remover(existing)  
        elif hasattr(collection, "remove"):
            collection.remove(existing)  
        elif hasattr(collection, "unlink"):
            collection.unlink(existing)  
            if not existing.use_fake_user and existing.users == 0:
                if isinstance(existing, Collection):
                    bpy.data.collections.remove(existing)
                elif isinstance(existing, Object):
                    bpy.data.objects.remove(existing)

    if internal:
        name = create_internal_id(name)

    if factory is not None:
        object = factory()
        object.name = name
        collection.link(object)
    elif hasattr(collection, "new"):
        object = collection.new(name, *args, **kwds)
    else:
        object = collection.load(*args, **kwds)
        object.name = name

    return object


def ensure_object_exists_in_collection(
    collection: bpy_prop_collection[T],
    name: str,
    factory: Callable[[], T] | None = None,
    internal: bool = False,
    *args,
    **kwds,
) -> tuple[T, bool]:
    
    existing = get_object_in_collection(
        collection, name, default=None, internal=internal
    )
    if existing is not None:
        return existing, False
    else:
        return (
            create_object_in_collection(
                collection,
                name,
                factory,
                internal=internal,
                *args,  
                **kwds,
            ),
            True,
        )


def find_empty_slot_in(collection: bpy_prop_collection, start_from: int = 0) -> int:
    
    for index in count(start_from):
        if collection[index] is None:
            return index

    raise RuntimeError("should never reach this point")


@overload
def get_object_in_collection(
    collection: bpy_prop_collection[T], name: str, internal: bool = False, **kwds
) -> T: ...


@overload
def get_object_in_collection(
    collection: bpy_prop_collection[T], name: str, internal: bool = False, *, default: D
) -> T | D: ...


def get_object_in_collection(
    collection: bpy_prop_collection[T], name: str, internal: bool = False, **kwds
):
    
    our_id = create_internal_id(name) if internal else name

    index = collection.find(our_id)
    if index >= 0:
        return collection[index]
    elif "default" in kwds:
        return kwds["default"]
    else:
        raise KeyError("No such object in collection: {0!r}".format(name))


def _get_actions_required_to_sort_collection_with_move_method(
    items: Sequence[Any], key: Callable[[Any], Any] | None = None
) -> list[tuple[int, int]]:
    
    result = []
    num_items = len(items)

    if num_items:
        if key:
            items = [key(item) for item in items]

        indexes = sorted(range(num_items), key=items.__getitem__)

        for front, index in enumerate(indexes):
            if index != front:
                result.append((index, front))
                for j in range(front + 1, num_items):
                    if indexes[j] >= front and indexes[j] < index:
                        indexes[j] += 1

    return result











def _get_actions_required_to_sort_collection_with_relinking(
    items: Sequence[Any], key: Callable[[Any], Any] | None = None
) -> list[Any]:
    
    if len(items) < 2:
        return []

    if key:
        sorted_items = sorted(items, key=key, reverse=True)
    else:
        sorted_items = sorted(items, reverse=True)

    start = 0
    items = list(items)
    while sorted_items:
        try:
            start = items.index(sorted_items[-1], start) + 1
        except ValueError:
            sorted_items.reverse()
            return sorted_items
        else:
            sorted_items.pop()
    else:
        return []


def sort_collection(collection: Collection, key: Callable[[Any], int]) -> None:
    
    if hasattr(collection, "move"):
        
        
        moves = _get_actions_required_to_sort_collection_with_move_method(
            collection, key
        )
        for source, target in moves:
            collection.move(source, target)  
    elif hasattr(collection, "link") and hasattr(collection, "unlink"):
        
        
        
        items = _get_actions_required_to_sort_collection_with_relinking(collection, key)
        for item in items:
            collection.unlink(item)
            collection.link(item)
    else:
        raise TypeError("collection needs move(), link() or unlink() methods")


def filter_collection(collection: Collection, filter: Callable[[Any], bool]) -> None:
    
    to_remove: list[Any] = []
    for item in collection:
        if not filter(item):
            to_remove.append(item)

    to_remove.reverse()
    for item in to_remove:
        collection.remove(item)


def pick_unique_name(
    proposal: str,
    collection: Iterable[T],
    *,
    getter: Callable[[T], str] = attrgetter("name"),
) -> str:
    
    existing_names = {getter(item) for item in collection}
    if proposal not in existing_names:
        return proposal

    proposal = proposal.rstrip()
    match = re.search("[0-9]*$", proposal)
    suffix = match.group() if match is not None else ""
    if suffix:
        prefix = proposal[: len(proposal) - len(suffix)]
    else:
        prefix, suffix = f"{proposal}.", "000"

    value = int(suffix)
    while True:
        value += 1
        new_proposal = prefix + (str(value).rjust(len(suffix), "0"))
        if new_proposal not in existing_names:
            return new_proposal
