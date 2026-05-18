from bpy.types import Header


class MinimumClearanceIndicator(Header):
    

    bl_idname = "OBJECT_HT_skybrush_clearance_indicator"
    bl_label = "Clearance"

    
    
    bl_space_type = "VIEW_3D"
    bl_context = "scene"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Not implemented yet")
