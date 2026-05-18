

from functools import lru_cache

import bpy

from sbstudio.plugin.constants import Collections, Templates
from sbstudio.plugin.materials import (
    get_material_for_led_light_color,
    set_emission_strength_of_material,
)
from sbstudio.plugin.views import find_all_3d_views

__all__ = (
    "bloom_effect_supported",
    "disable_bloom_effect",
    "enable_bloom_effect",
    "enable_bloom_effect_if_needed",
    "set_bloom_effect_enabled",
    "update_emission_strength",
)


def bloom_effect_supported() -> bool:
    
    
    
    return not _bloom_requires_compositor()


def enable_bloom_effect() -> None:
    
    set_bloom_effect_enabled(True)


def enable_bloom_effect_if_needed() -> None:
    
    if bpy.context.scene.skybrush.settings.use_bloom_effect:
        drones = Collections.find_drones(create=False)
        if drones:
            enable_bloom_effect()


def disable_bloom_effect() -> None:
    
    set_bloom_effect_enabled(False)


def set_bloom_effect_enabled(value: bool) -> None:
    
    if value:
        if _bloom_requires_compositor():
            
            pass
        else:
            _enable_bloom_with_eevee_renderer()

    else:
        if _bloom_requires_compositor():
            
            pass
        else:
            _disable_bloom_with_eevee_renderer()


def update_emission_strength(value: float) -> None:
    
    drones = Collections.find_drones().objects
    for drone in drones:
        material = get_material_for_led_light_color(drone)
        set_emission_strength_of_material(material, value)

    template = Templates.find_drone(create=False)
    if template:
        material = get_material_for_led_light_color(template)
        set_emission_strength_of_material(material, value)


@lru_cache(maxsize=1)
def _bloom_requires_compositor() -> bool:
    
    scene = bpy.context.scene
    return not hasattr(scene, "eevee") or not hasattr(scene.eevee, "use_bloom")


def _enable_bloom_with_eevee_renderer() -> None:
    
    bpy.context.scene.eevee.use_bloom = True
    bpy.context.scene.eevee.bloom_radius = 4
    bpy.context.scene.eevee.bloom_intensity = 0.2
    for space in find_all_3d_views():
        space.shading.type = "MATERIAL"


def _disable_bloom_with_eevee_renderer() -> None:
    
    bpy.context.scene.eevee.use_bloom = False
