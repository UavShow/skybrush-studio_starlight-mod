

from random import randint

import bpy

from sbstudio.plugin.constants import RANDOM_SEED_MAX, Collections
from sbstudio.plugin.utils.bloom import enable_bloom_effect_if_needed
from sbstudio.plugin.utils.pyro_markers import update_pyro_particles_of_object

from .base import Task


def setup_drone_collection(*args):
    
    drones = Collections.find_drones(create=False)
    scene = bpy.context.scene

    if drones and scene and scene.skybrush.settings.drone_collection is None:
        scene.skybrush.settings.drone_collection = drones


def remove_legacy_formation_constraints(*args):
    
    drones = Collections.find_drones(create=False)
    if not drones:
        return

    to_delete = []
    for drone in drones.objects:
        to_delete.clear()

        for constraint in drone.constraints:
            if constraint.type == "COPY_LOCATION" and "[To " in constraint.name:
                to_delete.append(constraint)

        if to_delete:
            for constraint in reversed(to_delete):
                drone.constraints.remove(constraint)


def setup_random_seed(*args):
    

    
    
    
    scene = bpy.context.scene
    if scene and scene.skybrush.settings.random_seed == 0:
        scene.skybrush.settings.random_seed = randint(1, RANDOM_SEED_MAX)


def update_bloom_effect(*args):
    enable_bloom_effect_if_needed()


def update_pyro_particles_of_drones(*args):
    
    drones = Collections.find_drones(create=False)
    if not drones:
        return

    for drone in drones.objects:
        update_pyro_particles_of_object(drone)


def regenerate_storyboard_entries_or_transitions(*args):
    
    scene = bpy.context.scene
    if scene and scene.skybrush.storyboard:
        scene.skybrush.storyboard._regenerate_entries_or_transitions()


def _config_logging(*args):
    import logging

    logging.basicConfig(
        format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
        level=logging.INFO,
        datefmt="%H:%M:%S",
    )


def perform_migrations(*args):
    from sbstudio.plugin.operators import RunAllMigrationOperators

    if RunAllMigrationOperators.poll(bpy.context):
        bpy.ops.skybrush.run_all_migrations("INVOKE_DEFAULT")


class InitializationTask(Task):
    

    functions = {
        "load_post": [
            update_bloom_effect,
            setup_drone_collection,
            remove_legacy_formation_constraints,
            setup_random_seed,
            update_pyro_particles_of_drones,
            regenerate_storyboard_entries_or_transitions,
            
            
            perform_migrations,
        ]
    }
