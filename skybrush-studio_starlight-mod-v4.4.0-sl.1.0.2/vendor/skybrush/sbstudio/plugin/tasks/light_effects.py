

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from sbstudio.model.types import MutableRGBAColor, RGBAColor
from sbstudio.plugin.colors import get_colors_of_drones_fast, set_color_of_drone
from sbstudio.plugin.constants import Collections
from sbstudio.plugin.utils.evaluator import get_position_of_object

from .base import Task
from .utils import Suspension

if TYPE_CHECKING:
    from bpy.types import Depsgraph, Scene

__all__ = ("UpdateLightEffectsTask", "suspended_light_effects")


_base_color_cache: dict[int, RGBAColor] = {}
"""Cache for the "base" color of every drone in the current frame before we
apply the light effects on them. Cleared when we move to a new frame. The
mapping is keyed by the _ids_ of the drones so we do not hang on to a
reference of a drone if the user deletes it and Blender decides to free the
associated memory area."""

_last_frame: int | None = None
"""Number of the last frame that was evaluated with `update_light_effects()`"""

suspension = Suspension()
"""Object to manage the suspension logic for the light effect task."""

WHITE: RGBAColor = (1, 1, 1, 1)
"""White color, used as a base color when no info is available for a newly added
drone.
"""


@suspension.wrap
def update_light_effects(scene: Scene, depsgraph: Depsgraph):
    global _last_frame, _base_color_cache, WHITE

    
    
    
    

    light_effects = scene.skybrush.light_effects
    if not light_effects or not light_effects.enabled:
        return

    random_seq = scene.skybrush.settings.random_sequence_root

    frame = scene.frame_current
    drones = None

    if _last_frame != frame:
        
        _last_frame = frame
        _base_color_cache.clear()

    changed = False

    for effect in light_effects.iter_active_effects_in_frame(frame):
        if drones is None:
            
            drones = Collections.find_drones().objects
            positions = [get_position_of_object(drone) for drone in drones]
            mapping = scene.skybrush.storyboard.get_mapping_at_frame(frame)
            if not _base_color_cache:
                
                
                arr = np.zeros((len(drones), 4), dtype=np.float32)
                get_colors_of_drones_fast(drones, dest=arr.ravel())
                colors: list[MutableRGBAColor] = arr.tolist()
                for drone, color in zip(drones, colors):
                    _base_color_cache[id(drone)] = color
            else:
                
                colors = [
                    _base_color_cache.get(id(drone)) or list(WHITE) for drone in drones
                ]

            changed = True

        effect.apply_on_colors(
            colors,
            positions=positions,
            mapping=mapping,
            frame=frame,
            random_seq=random_seq,
        )

    
    
    
    
    
    if not changed:
        if _base_color_cache:
            drones = Collections.find_drones().objects
            colors = [
                _base_color_cache.get(id(drone)) or list(WHITE) for drone in drones
            ]
            _base_color_cache.clear()
            changed = True

    if changed:
        assert drones is not None
        for drone, color in zip(drones, colors):
            set_color_of_drone(drone, color)


suspended_light_effects = suspension.use
"""Context manager that suspends the calculation of light effects when the
context is entered and re-enables them when the context is exited.
"""


class UpdateLightEffectsTask(Task):
    

    functions = {
        "depsgraph_update_post": update_light_effects,
        "frame_change_post": update_light_effects,
    }
