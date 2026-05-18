from functools import wraps
from typing import Callable, ParamSpec, TypeVar

import bpy

__all__ = ("with_context", "with_scene", "with_screen")

P = ParamSpec("P")
T = TypeVar("T")


def with_context(func: Callable[P, T]) -> Callable[P, T]:
    

    @wraps(func)
    def wrapper(*args, **kwds):
        context = kwds.get("context")

        if context is None:
            kwds["context"] = bpy.context

        return func(*args, **kwds)

    return wrapper


def with_scene(func: Callable[P, T]) -> Callable[P, T]:
    

    @wraps(func)
    def wrapper(*args, **kwds):
        scene = kwds.get("scene")

        if scene is None:
            kwds["scene"] = bpy.context.scene

        if kwds["scene"] is None:
            raise ValueError("no scene given")

        return func(*args, **kwds)

    return wrapper


def with_screen(func: Callable[P, T]) -> Callable[P, T]:
    

    @wraps(func)
    def wrapper(*args, **kwds):
        screen = kwds.get("screen")

        if screen is None:
            kwds["screen"] = bpy.context.screen
        elif isinstance(screen, str):
            try:
                kwds["screen"] = bpy.data.screens[screen]
            except KeyError:
                kwds["screen"] = None

        if kwds["screen"] is None:
            raise ValueError("no screen given")

        return func(*args, **kwds)

    return wrapper
