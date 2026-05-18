from sbstudio.plugin.constants import Collections
from sbstudio.plugin.utils import sort_collection
from sbstudio.plugin.utils.transition import get_id_for_formation_constraint

from .base import StoryboardOperator

__all__ = ("FixConstraintOrderingOperator",)


class FixConstraintOrderingOperator(StoryboardOperator):
    

    bl_idname = "skybrush.fix_constraint_ordering"
    bl_label = "Fix Ordering of Transition Constraints"
    bl_description = "Fixes the ordering of transition constraints in the show"

    only_with_valid_storyboard = True

    def execute_on_storyboard(self, storyboard, entries, context):
        
        drones = Collections.find_drones().objects

        
        
        formation_priority_map = {
            get_id_for_formation_constraint(entry): index
            for index, entry in enumerate(entries)
        }

        def key_function(constraint):
            return formation_priority_map.get(constraint.name, 100000)

        for drone in drones:
            sort_collection(drone.constraints, key=key_function)

        return {"FINISHED"}
