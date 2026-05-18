

import re
from collections.abc import Set
from contextlib import contextmanager
from typing import Iterator

import bpy


def _get_menu_by_name(menu):
    menu = re.sub(r"[^A-Za-z]+", "_", menu.lower())
    if hasattr(bpy.types, "TOPBAR_MT_" + menu):
        return getattr(bpy.types, "TOPBAR_MT_" + menu)
    else:
        return getattr(bpy.types, "INFO_MT_" + menu)


_already_processed_with_make_annotations: Set[type] = set()


def _make_annotations(cls):
    
    
    
    
    try:
        from bpy.props import _PropertyDeferred as PropertyType
    except ImportError:
        PropertyType = tuple

    classes = list(reversed(cls.__mro__))
    bl_props = {}
    while classes:
        current_class = classes.pop()
        if (
            current_class != cls
            and current_class not in _already_processed_with_make_annotations
        ):
            _make_annotations(current_class)

    _already_processed_with_make_annotations.add(cls)
    bl_props.update(
        {k: v for k, v in cls.__dict__.items() if isinstance(v, PropertyType)}
    )

    if bl_props:
        if "__annotations__" not in cls.__dict__:
            cls.__annotations__ = {}
        annotations = cls.__dict__["__annotations__"]
        for k, v in bl_props.items():
            annotations[k] = v
            delattr(cls, k)

    return cls


def register_in_menu(menu, func):
    _get_menu_by_name(menu).append(func)


def register_header(cls):
    
    _make_annotations(cls)
    bpy.utils.register_class(cls)


def register_list(cls):
    
    _make_annotations(cls)
    bpy.utils.register_class(cls)


def register_menu(cls):
    
    _make_annotations(cls)
    bpy.utils.register_class(cls)


def register_operator(cls):
    
    _make_annotations(cls)
    bpy.utils.register_class(cls)


def register_panel(cls):
    
    _make_annotations(cls)
    bpy.utils.register_class(cls)


def register_translations(translations_dict):
    
    bpy.app.translations.register(__name__, translations_dict)


def register_type(cls):
    
    _make_annotations(cls)
    bpy.utils.register_class(cls)


def unregister_from_menu(menu, func):
    _get_menu_by_name(menu).remove(func)


def unregister_header(cls):
    
    bpy.utils.unregister_class(cls)


def unregister_list(cls):
    
    bpy.utils.unregister_class(cls)


def unregister_menu(cls):
    
    bpy.utils.unregister_class(cls)


def unregister_operator(cls):
    
    bpy.utils.unregister_class(cls)


def unregister_panel(cls):
    
    bpy.utils.unregister_class(cls)


def unregister_translations():
    
    bpy.app.translations.unregister(__name__)


def unregister_type(cls):
    
    bpy.utils.unregister_class(cls)


def enter_edit_mode(obj=None, *, context=None):
    
    if obj is not None:
        context = context or bpy.context
        context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT", toggle=False)


def is_online_access_allowed() -> bool:
    
    
    
    return bool(getattr(bpy.app, "online_access", True))


@contextmanager
def temporarily_exit_edit_mode(context=None) -> Iterator[None]:
    
    context = context or bpy.context
    mode = context.mode
    if mode != "EDIT_MESH":
        yield
    else:
        ob = context.view_layer.objects.active
        with use_mode_for_object("OBJECT"):
            yield
        enter_edit_mode(ob, context=context)


@contextmanager
def use_menu(menu, func):
    
    register_in_menu(menu, func)
    try:
        yield
    finally:
        unregister_from_menu(menu, func)


@contextmanager
def use_mode_for_object(mode) -> Iterator[str]:
    
    context = bpy.context

    original_mode = context.object.mode
    if original_mode == mode:
        yield original_mode
    else:
        bpy.ops.object.mode_set(mode=mode)
        try:
            with context.temp_override():
                yield original_mode
        finally:
            bpy.ops.object.mode_set(mode=original_mode)


@contextmanager
def use_operator(cls):
    
    register_operator(cls)
    try:
        yield
    finally:
        unregister_operator(cls)
