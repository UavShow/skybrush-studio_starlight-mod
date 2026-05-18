from typing import Sequence

import bpy
import numpy as np
import numpy.typing as npt
from bpy.types import Object

from sbstudio.model.types import Color, RGBAColor, RGBAColorLike, SupportsForEach
from sbstudio.plugin.actions import ensure_animation_data_exists_for_object
from sbstudio.plugin.keyframes import set_keyframes

__all__ = (
    "create_keyframe_for_color_of_drone",
    "get_color_of_drone",
    "set_color_of_drone",
)


def create_keyframe_for_color_of_drone(
    drone: Object,
    color: Color,
    *,
    frame: int | None = None,
    step: bool = False,
):
    
    if frame is None:
        frame = bpy.context.scene.frame_current

    ensure_animation_data_exists_for_object(drone)

    color_as_rgba: RGBAColor

    if hasattr(color, "r"):
        color_as_rgba = color.r, color.g, color.b, 1.0
    else:
        color_as_rgba = color[0], color[1], color[2], 1.0

    keyframes: list[tuple[int, RGBAColor | None]] = [(frame, color_as_rgba)]
    if step and frame > bpy.context.scene.frame_start:
        keyframes.insert(0, (frame - 1, None))

    set_keyframes(drone, "color", keyframes, interpolation="LINEAR")


def get_color_of_drone(drone: Object) -> Sequence[float]:
    
    if drone.color is not None:
        return drone.color

    return (0.0, 0.0, 0.0, 0.0)


def get_colors_of_drones_fast(
    drones: SupportsForEach, *, dest: npt.NDArray | None = None
) -> npt.NDArray:
    
    if dest is None:
        dest = np.empty((len(drones), 4), dtype=np.float32)
    drones.foreach_get("color", dest.ravel())
    return dest


def set_color_of_drone(drone: Object, color: RGBAColorLike):
    
    if any(
        abs(a - b) > 1e-3 for a, b in zip(color, get_color_of_drone(drone), strict=True)
    ):
        drone.color = color


def set_colors_of_drones_fast(drones: SupportsForEach, colors: npt.NDArray) -> None:
    
    drones.foreach_set("color", colors)
