from bpy.types import Operator

from sbstudio.plugin.constants import Collections
from sbstudio.plugin.objects import link_object_to_scene
from sbstudio.plugin.state import get_file_specific_state

__all__ = ("PrepareSceneOperator",)


class PrepareSceneOperator(Operator):
    

    bl_idname = "skybrush.prepare"
    bl_label = "Prepare scene for Skybrush"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        get_file_specific_state().ensure_initialized()

        
        drones = Collections.find_drones()
        formations = Collections.find_formations()
        templates = Collections.find_templates()

        link_object_to_scene(drones, allow_nested=True)
        link_object_to_scene(formations, allow_nested=True)
        link_object_to_scene(templates, allow_nested=True)

        
        

        return {"FINISHED"}
