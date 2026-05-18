

from __future__ import annotations

from collections.abc import Mapping
from math import hypot
from typing import TYPE_CHECKING

import bpy
from bpy.types import Collection

from sbstudio.math.nearest_neighbors import find_nearest_neighbors
from sbstudio.model.types import Coordinate3D
from sbstudio.plugin.constants import Collections
from sbstudio.plugin.utils.evaluator import (
    get_position_of_object,
    get_xyz_euler_rotation_of_object,
)
from sbstudio.utils import LRUCache

from .base import Task
from .utils import Suspension

if TYPE_CHECKING:
    from bpy.types import Depsgraph, Scene

__all__ = (
    "SafetyCheckTask",
    "create_position_snapshot_for_drones_in_collection",
    "suspended_safety_checks",
    "invalidate_caches",
)




VectorSnapshot = dict[str, Coordinate3D]
PositionSnapshot = VectorSnapshot
VelocitySnapshot = VectorSnapshot
RotationSnapshot = VectorSnapshot

_position_snapshot_cache: LRUCache[int, PositionSnapshot] = LRUCache(5)
"""Cache that stores the positions in the last few frames visited by the user
in the hope that we can estimate the velocities from it in the current frame.
"""

_velocity_snapshot_cache: LRUCache[int, PositionSnapshot] = LRUCache(5)
"""Cache that stores the velocities in the last few frames visited by the user
in the hope that we can estimate the accelerations from it in the current frame.

Velocities are estimated from the positions so this cache is probably even more
sparsely populated than the position cache.
"""

_rotation_snapshot_cache: LRUCache[int, RotationSnapshot] = LRUCache(5)
"""Cache that stores the Euler rotation angles in the last few frames visited by the user
in the hope that we can estimate the yaw rates from it in the current frame.
"""

_ZERO = (0.0, 0.0, 0.0)
"""Zero velocity tuple, used frequently in velocity estimations when no data is
available.
"""

suspension = Suspension()
"""Object to manage the suspension logic for the safety check task."""


def create_position_snapshot_for_drones_in_collection(
    collection: Collection,
) -> PositionSnapshot:
    
    return {drone.name: get_position_of_object(drone) for drone in collection.objects}


def create_rotation_snapshot_for_drones_in_collection(
    collection, *, frame: int
) -> RotationSnapshot:
    
    return {
        drone.name: get_xyz_euler_rotation_of_object(drone)
        for drone in collection.objects
    }


def estimate_derivatives_at_frame(
    snapshot: VectorSnapshot,
    cache: Mapping[int, VectorSnapshot],
    *,
    frame: int,
    scene: Scene,
) -> tuple[VectorSnapshot, bool]:
    
    global _ZERO

    if frame <= scene.frame_start:
        
        return dict.fromkeys(snapshot, _ZERO), True

    threshold = 5  
    best, best_diff = None, threshold + 1

    for item in cache.items():
        other_frame, other_snapshot = item
        diff = abs(other_frame - frame)
        if diff == 0:
            continue

        
        is_better = diff < best_diff or (diff == best_diff and other_frame < frame)

        if is_better:
            best, best_diff = item, diff

    if best is None:
        
        return dict.fromkeys(snapshot, _ZERO), False

    
    other_frame, other_snapshot = best
    diff = (frame - other_frame) / scene.render.fps

    result = {}
    should_cache = True
    for drone_name, curr in snapshot.items():
        prev = other_snapshot.get(drone_name)
        if prev is None:
            result[drone_name] = _ZERO
            should_cache = False
        else:
            result[drone_name] = (
                (curr[0] - prev[0]) / diff,
                (curr[1] - prev[1]) / diff,
                (curr[2] - prev[2]) / diff,
            )

    return result, should_cache


@suspension.wrap
def run_safety_check(scene: Scene, depsgraph: Depsgraph) -> None:
    safety_check = scene.skybrush.safety_check

    if safety_check.enabled:
        drones = Collections.find_drones(create=False)
    else:
        drones = None

    if not drones:
        safety_check.clear_safety_check_result()
        return

    
    if safety_check.altitude_warning_threshold:
        min_altitude = safety_check.min_navigation_altitude
        max_altitude = safety_check.altitude_warning_threshold
    else:
        min_altitude = None
        max_altitude = None

    
    if safety_check.velocity_warning_enabled:
        max_velocity_xy = safety_check.velocity_xy_warning_threshold
        max_velocity_z_down = safety_check.effective_velocity_z_threshold_down
        max_velocity_z_up = safety_check.effective_velocity_z_threshold_up
    else:
        max_velocity_xy, max_velocity_z_up, max_velocity_z_down = None, None, None

    
    if safety_check.acceleration_warning_enabled:
        max_acceleration = safety_check.acceleration_warning_threshold
    else:
        max_acceleration = None

    
    if safety_check.yaw_rate_warning_enabled:
        max_yaw_rate = safety_check.yaw_rate_warning_threshold
    else:
        max_yaw_rate = None

    
    frame = scene.frame_current
    position_snapshot = create_position_snapshot_for_drones_in_collection(drones)
    _position_snapshot_cache[frame] = position_snapshot

    
    velocity_snapshot, velocity_snapshot_valid = estimate_derivatives_at_frame(
        position_snapshot, _position_snapshot_cache, frame=frame, scene=scene
    )
    if velocity_snapshot_valid:
        _velocity_snapshot_cache[frame] = velocity_snapshot

    
    acceleration_snapshot, acceleration_snapshot_valid = estimate_derivatives_at_frame(
        velocity_snapshot, _velocity_snapshot_cache, frame=frame, scene=scene
    )

    
    rotation_snapshot = create_rotation_snapshot_for_drones_in_collection(
        drones, frame=frame
    )
    _rotation_snapshot_cache[frame] = rotation_snapshot
    rotation_rate_snapshot, rotation_rate_snapshot_valid = (
        estimate_derivatives_at_frame(
            rotation_snapshot, _rotation_snapshot_cache, frame=frame, scene=scene
        )
    )

    
    storyboard = scene.skybrush.storyboard
    formation_status = storyboard.get_formation_status_at_frame(frame)

    
    positions = list(position_snapshot.values())
    velocities = list(velocity_snapshot.values()) if velocity_snapshot_valid else []
    accelerations = (
        [hypot(*vec) for vec in acceleration_snapshot.values()]
        if acceleration_snapshot_valid
        else []
    )
    rotation_rates = (
        list(rotation_rate_snapshot.values()) if rotation_rate_snapshot_valid else []
    )

    
    max_altitude_found = (
        max(position[2] for position in positions) if positions else 0.0
    )
    min_altitude_found = (
        min(position[2] for position in positions) if positions else 0.0
    )

    
    if max_altitude is not None:
        drones_over_max_altitude = [
            position for position in positions if position[2] >= max_altitude
        ]
    else:
        drones_over_max_altitude = []

    
    positions_for_proximity_check = safety_check.get_positions_for_proximity_check(
        positions
    )
    nearest_neighbors = find_nearest_neighbors(positions_for_proximity_check)

    
    max_velocity_xy_found = (
        max(hypot(vel[0], vel[1]) for vel in velocities) if velocities else 0.0
    )
    drones_over_max_velocity_xy = (
        [
            position_snapshot.get(name, _ZERO)
            for name, vel in velocity_snapshot.items()
            if hypot(vel[0], vel[1]) > max_velocity_xy
        ]
        if max_velocity_xy is not None
        else []
    )

    
    max_velocity_z_up_found = (
        max(0.0, max(vel[2] for vel in velocities)) if velocities else 0.0
    )
    max_velocity_z_down_found = (
        min(0.0, min(vel[2] for vel in velocities)) if velocities else 0.0
    )
    drones_over_max_velocity_z = (
        [
            position_snapshot.get(name, _ZERO)
            for name, vel in velocity_snapshot.items()
            if vel[2] > max_velocity_z_up or vel[2] < -max_velocity_z_down
        ]
        if max_velocity_z_up is not None and max_velocity_z_down is not None
        else []
    )

    
    max_acceleration_found = max(accelerations) if accelerations else 0.0
    drones_over_max_acceleration = (
        [
            position_snapshot.get(name, _ZERO)
            for name, acc in acceleration_snapshot.items()
            if hypot(acc[0], acc[1], acc[2]) > max_acceleration
        ]
        if max_acceleration is not None and max_acceleration_found > max_acceleration
        else []
    )

    
    max_yaw_rate_found = (
        round(max(abs(rate[2]) for rate in rotation_rates), ndigits=2)
        if rotation_rates
        else 0.0
    )
    drones_over_max_yaw_rate = (
        [
            position_snapshot.get(name, _ZERO)
            for name, rate in rotation_rate_snapshot.items()
            if round(abs(rate[2]), ndigits=2) > max_yaw_rate
        ]
        if max_yaw_rate is not None
        else []
    )

    
    drones_below_min_nav_altitude = (
        [
            pos
            for name, vel in velocity_snapshot.items()
            if hypot(vel[0], vel[1]) > 1e-2
            and (pos := position_snapshot.get(name, _ZERO))[2] < min_altitude
        ]
        if min_altitude is not None and min_altitude_found < min_altitude
        else []
    )

    safety_check.set_safety_check_result(
        formation_status=formation_status,
        nearest_neighbors=nearest_neighbors,
        min_altitude=min_altitude_found,
        max_altitude=max_altitude_found,
        drones_over_max_altitude=drones_over_max_altitude,
        max_velocity_xy=max_velocity_xy_found,
        drones_over_max_velocity_xy=drones_over_max_velocity_xy,
        max_velocity_z_up=max_velocity_z_up_found,
        max_velocity_z_down=abs(max_velocity_z_down_found),
        drones_over_max_velocity_z=drones_over_max_velocity_z,
        max_acceleration=max_acceleration_found,
        drones_over_max_acceleration=drones_over_max_acceleration,
        max_yaw_rate=max_yaw_rate_found,
        drones_over_max_yaw_rate=drones_over_max_yaw_rate,
        drones_below_min_nav_altitude=drones_below_min_nav_altitude,
        all_close_pairs=[],
    )


def ensure_overlays_enabled():
    
    safety_check = bpy.context.scene.skybrush.safety_check
    safety_check.ensure_overlays_enabled_if_needed()


def invalidate_caches(clear_result: bool = False):
    
    global _position_snapshot_cache, _velocity_snapshot_cache, _rotation_snapshot_cache
    _position_snapshot_cache.clear()
    _velocity_snapshot_cache.clear()
    _rotation_snapshot_cache.clear()

    if clear_result:
        safety_check = bpy.context.scene.skybrush.safety_check
        safety_check.clear_safety_check_result()


def run_tasks_post_load(*args):
    
    invalidate_caches()
    ensure_overlays_enabled()


suspended_safety_checks = suspension.use
"""Context manager that suspends safety checks when the context is entered
and re-enables them when the context is exited.
"""


class SafetyCheckTask(Task):
    

    functions = {
        "depsgraph_update_post": run_safety_check,
        "frame_change_post": run_safety_check,
        "load_post": run_tasks_post_load,
    }
