

from __future__ import annotations

from abc import ABCMeta
from collections.abc import Callable
from typing import ClassVar

import bpy
import gpu
from bpy.types import SpaceView3D

__all__ = ("Overlay",)


class Overlay(metaclass=ABCMeta):
    

    _enabled: bool
    """Whether the overlay is enabled."""

    _handler_2d: object
    """Handle to the registered Blender 2D draw handler, used when unregistering
    the overlay.
    """

    _handler_3d: object
    """Handle to the registered Blender 3D draw handler, used when unregistering
    the overlay.
    """

    def __init__(self):
        
        self._enabled = False
        self._handler_2d = None
        self._handler_3d = None

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        value = bool(value)

        if self._enabled == value:
            return

        if self._enabled:
            if self._handler_2d:
                SpaceView3D.draw_handler_remove(self._handler_2d, "WINDOW")
                self._handler_2d = None
            if self._handler_3d:
                SpaceView3D.draw_handler_remove(self._handler_3d, "WINDOW")
                self._handler_3d = None
            self.dispose()

        self._enabled = value

        if self._enabled:
            self.prepare()
            if hasattr(self, "draw_3d"):
                handler: Callable[[], None] = self.draw_3d  
                self._handler_3d = SpaceView3D.draw_handler_add(
                    handler, (), "WINDOW", getattr(self, "event", "POST_VIEW")
                )
            if hasattr(self, "draw_2d"):
                handler: Callable[[], None] = self.draw_2d  
                self._handler_2d = SpaceView3D.draw_handler_add(
                    handler, (), "WINDOW", getattr(self, "event", "POST_PIXEL")
                )

    def prepare(self) -> None:
        
        pass

    def dispose(self) -> None:
        
        pass


class ShaderOverlay(Overlay):
    

    shader_type: ClassVar[str] = "POINT_UNIFORM_COLOR"

    _shader: gpu.types.GPUShader | None = None

    def __init__(self):
        super().__init__()

        self._shader = None

    def get_ui_scale(self) -> float:
        
        
        
        return bpy.context.preferences.system.ui_scale

    def prepare(self) -> None:
        self._shader = gpu.shader.from_builtin(self.shader_type)

    def dispose(self) -> None:
        self._shader = None
