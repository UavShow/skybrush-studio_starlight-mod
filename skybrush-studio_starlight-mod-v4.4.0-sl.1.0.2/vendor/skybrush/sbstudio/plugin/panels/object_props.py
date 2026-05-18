from bpy.types import Panel

from sbstudio.plugin.operators import UseSelectedVertexGroupForFormationOperator

__all__ = ("DroneShowAddonObjectPropertiesPanel",)


class DroneShowAddonObjectPropertiesPanel(Panel):
    

    bl_idname = "DATA_PT_skybrush_properties"
    bl_label = "Drone Show"
    bl_options = {"DEFAULT_CLOSED"}

    
    
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True

        ob = context.object
        layout.label(text="Name of Formation Vertex Group:")

        row = layout.row(align=True)
        row.prop(ob.skybrush, "formation_vertex_group", text="")
        row.operator(
            UseSelectedVertexGroupForFormationOperator.bl_idname, text="Use selected"
        )

        layout.label(text="Pyro trigger events:")
        row = layout.row(align=True)
        row.prop(ob.skybrush, "pyro_markers", text="")

    @classmethod
    def poll(cls, context):
        return (
            context.object
            and context.object.type == "MESH"
            and getattr(context.object, "skybrush", None)
        )
