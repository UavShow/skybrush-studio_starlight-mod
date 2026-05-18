from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence

import bpy
from bpy.types import Context, Object

from sbstudio.model.color import Color4D
from sbstudio.model.light_program import LightProgram
from sbstudio.model.point import Point4D
from sbstudio.model.trajectory import Trajectory
from sbstudio.model.yaw import YawSetpoint, YawSetpointList
from sbstudio.plugin.colors import get_color_of_drone
from sbstudio.plugin.utils.evaluator import (
    get_position_of_object,
    get_xyz_euler_rotation_of_object,
)
from sbstudio.plugin.utils.progress import FrameIterator, FrameProgressReport

from .decorators import with_context

__all__ = (
    "each_frame_in",
    "frame_range",
    "sample_colors_of_objects",
    "sample_positions_of_objects",
    "sample_positions_and_yaw_of_objects",
    "sample_positions_of_objects_in_frame_range",
    "sample_positions_and_colors_of_objects",
    "sample_positions_colors_and_yaw_of_objects",
)


def _to_int_255(value: float) -> int:
    
    return int(max(0, min(255, round(value * 255))))


@with_context
def frame_range(
    start: int,
    end: int,
    *,
    fps: int,
    context: Context | None = None,
    operation: str | None = None,
    progress: Callable[[FrameProgressReport], None] | None = None,
) -> Iterator[int]:
    
    assert context is not None  

    scene_fps = context.scene.render.fps
    frame_step = max(1, int(scene_fps // fps))
    return FrameIterator(start, end, frame_step, operation=operation, progress=progress)


@with_context
def each_frame_in(
    frames: Iterable[int], *, redraw: bool = False, context: Context | None = None
) -> Iterable[tuple[int, float]]:
    
    assert context is not None  

    scene = context.scene
    fps = scene.render.fps

    for frame in frames:
        scene.frame_set(frame)
        if redraw:
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=0)

        time = frame / fps
        yield frame, time


@with_context
def sample_positions_of_objects(
    objects: Sequence[Object],
    frames: Iterable[int],
    *,
    by_name: bool = False,
    simplify: bool = False,
    context: Context | None = None,
) -> dict[Object, Trajectory] | dict[str, Trajectory]:
    
    trajectories = defaultdict(Trajectory)

    for _, time in each_frame_in(frames, context=context):
        for obj in objects:
            key = obj.name if by_name else obj
            trajectories[key].append(Point4D(time, *get_position_of_object(obj)))

    if simplify:
        return {key: value.simplify_in_place() for key, value in trajectories.items()}
    else:
        return dict(trajectories)


@with_context
def sample_positions_and_yaw_of_objects(
    objects: Sequence[Object],
    frames: Iterable[int],
    *,
    by_name: bool = False,
    simplify: bool = False,
    context: Context | None = None,
) -> dict[Object, tuple[Trajectory, YawSetpointList]]:
    
    trajectories = defaultdict(Trajectory)
    yaw_setpoints = defaultdict(YawSetpointList)

    for _, time in each_frame_in(frames, context=context):
        for obj in objects:
            key = obj.name if by_name else obj
            trajectories[key].append(Point4D(time, *get_position_of_object(obj)))
            rotation = get_xyz_euler_rotation_of_object(obj)
            
            yaw_setpoints[key].append(YawSetpoint(time, -rotation[2]))

    
    
    for yaw in yaw_setpoints.values():
        yaw.unwrap()

    if simplify:
        return {
            key: (
                trajectory.simplify_in_place(),
                yaw_setpoints[key].simplify(),
            )
            for key, trajectory in trajectories.items()
        }

    else:
        return {
            key: (trajectory, yaw_setpoints[key])
            for key, trajectory in trajectories.items()
        }


@with_context
def sample_colors_of_objects(
    objects: Sequence[Object],
    frames: Iterable[int],
    *,
    by_name: bool = False,
    simplify: bool = False,
    redraw: bool = False,
    context: Context | None = None,
) -> dict[Object | str, LightProgram]:
    
    lights = defaultdict(LightProgram)

    for _, time in each_frame_in(frames, context=context, redraw=redraw):
        for obj in objects:
            key = obj.name if by_name else obj
            color = get_color_of_drone(obj)
            lights[key].append(
                Color4D(
                    time,
                    _to_int_255(color[0]),
                    _to_int_255(color[1]),
                    _to_int_255(color[2]),
                )
            )

    if simplify:
        return {key: value.simplify() for key, value in lights.items()}
    else:
        return dict(lights)


@with_context
def sample_positions_and_colors_of_objects(
    objects: Sequence[Object],
    frames: Iterable[int],
    *,
    by_name: bool = False,
    simplify: bool = False,
    redraw: bool = False,
    context: Context | None = None,
) -> dict[Object, tuple[Trajectory, LightProgram]]:
    
    trajectories = defaultdict(Trajectory)
    lights = defaultdict(LightProgram)

    for _, time in each_frame_in(frames, context=context, redraw=redraw):
        for obj in objects:
            key = obj.name if by_name else obj
            pos = get_position_of_object(obj)
            color = get_color_of_drone(obj)
            trajectories[key].append(Point4D(time, *pos))
            lights[key].append(
                Color4D(
                    time,
                    _to_int_255(color[0]),
                    _to_int_255(color[1]),
                    _to_int_255(color[2]),
                )
            )

    if simplify:
        return {
            key: (trajectory.simplify_in_place(), lights[key].simplify())
            for key, trajectory in trajectories.items()
        }
    else:
        return {
            key: (trajectory, lights[key]) for key, trajectory in trajectories.items()
        }


@with_context
def sample_positions_colors_and_yaw_of_objects(
    objects: Sequence[Object],
    frames: Iterable[int],
    *,
    by_name: bool = False,
    simplify: bool = False,
    redraw: bool = False,
    context: Context | None = None,
) -> dict[Object, tuple[Trajectory, LightProgram, YawSetpointList]]:
    
    trajectories = defaultdict(Trajectory)
    lights = defaultdict(LightProgram)
    yaw_setpoints = defaultdict(YawSetpointList)

    for _, time in each_frame_in(frames, context=context, redraw=redraw):
        for obj in objects:
            key = obj.name if by_name else obj
            pos = get_position_of_object(obj)
            color = get_color_of_drone(obj)
            rotation = get_xyz_euler_rotation_of_object(obj)
            trajectories[key].append(Point4D(time, *pos))
            lights[key].append(
                Color4D(
                    time,
                    _to_int_255(color[0]),
                    _to_int_255(color[1]),
                    _to_int_255(color[2]),
                )
            )
            
            yaw_setpoints[key].append(YawSetpoint(time, -rotation[2]))

    
    
    for yaw in yaw_setpoints.values():
        yaw.unwrap()

    if simplify:
        return {
            key: (
                trajectory.simplify_in_place(),
                lights[key].simplify(),
                yaw_setpoints[key].simplify(),
            )
            for key, trajectory in trajectories.items()
        }
    else:
        return {
            key: (trajectory, lights[key], yaw_setpoints[key])
            for key, trajectory in trajectories.items()
        }


@with_context
def sample_positions_of_objects_in_frame_range(
    objects: Sequence[Object],
    bounds: tuple[int, int],
    *,
    fps: int,
    by_name: bool = False,
    simplify: bool = False,
    context: Context | None = None,
) -> dict[Object, Trajectory] | dict[str, Trajectory]:
    
    return sample_positions_of_objects(
        objects,
        frame_range(bounds[0], bounds[1], fps=fps, context=context),
        by_name=by_name,
        simplify=simplify,
        context=context,
    )
