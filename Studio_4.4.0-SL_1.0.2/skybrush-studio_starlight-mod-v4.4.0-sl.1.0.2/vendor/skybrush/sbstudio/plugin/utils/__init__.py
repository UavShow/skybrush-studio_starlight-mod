

from contextlib import contextmanager
from operator import attrgetter

import bpy
from bpy.types import Context

from .collections import (
    create_object_in_collection,
    ensure_object_exists_in_collection,
    find_empty_slot_in,
    get_object_in_collection,
    sort_collection,
)
from .debounce import debounced
from .decorators import with_context, with_scene, with_screen
from .identifiers import create_internal_id, propose_name, propose_names
from .platform import get_temporary_directory, open_file_with_default_application

__all__ = (
    "create_object_in_collection",
    "create_internal_id",
    "debounced",
    "descendants_of",
    "ensure_object_exists_in_collection",
    "find_empty_slot_in",
    "get_object_in_collection",
    "get_temporary_directory",
    "overridden_context",
    "open_file_with_default_application",
    "propose_name",
    "propose_names",
    "remove_if_unused",
    "sort_collection",
    "with_context",
    "with_scene",
    "with_screen",
)


def descendants_of(objects, selector="children"):
    
    if isinstance(selector, str):
        selector = attrgetter(selector)

    if not callable(selector):
        raise TypeError("selector must be string or callable")

    if hasattr(objects, "__iter__"):
        queue = list(objects)
    else:
        queue = [objects]

    seen = set()
    while queue:
        obj = queue.pop()
        if obj in seen:
            continue

        seen.add(obj)
        yield obj

        queue.extend(selector(obj))


@contextmanager
def overridden_context(current_context: Context | None = None, **kwds):
    
    result = (current_context or bpy.context).copy()
    for key, value in kwds.items():
        setattr(result, key, value)
    yield result


def remove_if_unused(obj, from_) -> bool:
    
    if obj and not obj.use_fake_user and obj.users == 1:
        from_.remove(obj, do_unlink=True)
        return True
    else:
        return False
