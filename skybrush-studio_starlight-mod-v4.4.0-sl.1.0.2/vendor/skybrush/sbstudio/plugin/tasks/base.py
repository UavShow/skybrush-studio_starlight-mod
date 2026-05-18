

from typing import Callable, ClassVar, Iterable, Iterator

import bpy
from bpy.app.handlers import persistent

__all__ = ("Task",)


_handler_names: list[str] = [
    "depsgraph_update_pre",
    "depsgraph_update_post",
    "frame_change_pre",
    "frame_change_post",
    "load_factory_preferences_pre",
    "load_factory_preferences_post",
    "load_pre",
    "load_post",
    "redo_pre",
    "redo_post",
    "render_cancel",
    "render_complete",
    "render_init",
    "render_pre",
    "render_post",
    "render_stats",
    "render_write",
    "save_pre",
    "save_post",
    "undo_pre",
    "version_update",
]


class Task:
    

    functions: ClassVar[dict[str, Callable[..., None] | Iterable[Callable[..., None]]]]
    """Override this property in subclasses to define the handlers to register."""

    _registered_handlers: list[tuple[str, Callable[..., None]]]

    def register(cls):
        
        cls._registered_handlers = []

        for name in _handler_names:
            funcs = cls.functions.get(name)
            if funcs is None:
                continue

            func_iter: Iterator[Callable[..., None]]
            try:
                func_iter = iter(funcs)  
            except TypeError:
                func_iter = iter([funcs])

            for func in func_iter:
                if callable(func):
                    func = persistent(func)
                    getattr(bpy.app.handlers, name).append(func)
                    cls._registered_handlers.append((name, func))

    def unregister(cls):
        
        for name, func in reversed(cls._registered_handlers):
            getattr(bpy.app.handlers, name).remove(func)

        del cls._registered_handlers
