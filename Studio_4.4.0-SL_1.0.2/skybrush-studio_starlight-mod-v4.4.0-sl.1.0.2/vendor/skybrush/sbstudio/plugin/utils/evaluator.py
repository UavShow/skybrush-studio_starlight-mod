from collections.abc import Callable, Sequence
from contextlib import contextmanager
from functools import partial
from math import degrees
from typing import Iterator, overload

import numpy as np
import numpy.typing as npt
from bpy.types import Context, Object

from sbstudio.model.types import Coordinate3D, Quaternion, Rotation3D, SupportsForEach

from .decorators import with_context

__all__ = (
    "create_position_evaluator",
    "get_position_of_object",
    "get_xyz_euler_rotation_of_object",
    "get_quaternion_rotation_of_object",
)


@contextmanager
@with_context
def create_position_evaluator(
    context: Context | None = None,
) -> Iterator[Callable[[Sequence[Object]], Sequence[Coordinate3D]]]:
    
    assert context is not None

    scene = context.scene
    original_frame = scene.frame_current
    seek_to = scene.frame_set

    try:
        yield partial(_evaluate_positions_of_objects, seek_to=seek_to)
    finally:
        seek_to(original_frame)


@overload
def _evaluate_positions_of_objects(
    objects: Sequence[Object],
) -> Sequence[Coordinate3D]: ...


@overload
def _evaluate_positions_of_objects(
    objects: Sequence[Object],
    *,
    seek_to: Callable[[int], None],
    frame: int,
) -> Sequence[Coordinate3D]: ...


def _evaluate_positions_of_objects(
    objects: Sequence[Object],
    *,
    seek_to: Callable[[int], None] | None = None,
    frame: int | None = None,
) -> Sequence[Coordinate3D]:
    if frame is not None:
        assert seek_to is not None
        seek_to(frame)
    return [get_position_of_object(obj) for obj in objects]


def get_position_of_object(object: Object) -> Coordinate3D:
    
    return tuple(object.matrix_world.translation)  


def get_xyz_euler_rotation_of_object(object: Object) -> Rotation3D:
    
    return tuple(degrees(angle) for angle in object.matrix_world.to_euler("XYZ"))  


def get_quaternion_rotation_of_object(object: Object) -> Quaternion:
    
    return tuple(object.matrix_world.to_quaternion())  


def get_positions_of_objects_fast(
    objects: SupportsForEach, *, dest: npt.NDArray | None = None
) -> npt.NDArray:
    
    matrices = np.empty((len(objects), 16), dtype=np.float32)
    objects.foreach_get("matrix_world", matrices.ravel())
    if dest is None:
        return matrices[:, 12:15]
    else:
        np.copyto(dest, matrices[:, 12:15])
        return dest
