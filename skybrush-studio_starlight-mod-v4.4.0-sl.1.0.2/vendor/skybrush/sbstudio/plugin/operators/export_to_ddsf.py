from typing import Any

from bpy.props import BoolProperty, IntProperty, StringProperty

from sbstudio.model.file_formats import FileFormat

from .base import ExportOperator

__all__ = ("DDSFExportOperator",)







class DDSFExportOperator(ExportOperator):
    

    bl_idname = "export_scene.ddsf"
    bl_label = "Export Depence .ddsf format"
    bl_options = {"REGISTER"}

    
    filter_glob = StringProperty(default="*.ddsf", options={"HIDDEN"})
    filename_ext = ".ddsf"

    
    output_fps = IntProperty(
        name="Trajectory FPS",
        default=4,
        description="Number of samples to take from trajectories per second",
    )

    
    light_output_fps = IntProperty(
        name="Light FPS",
        default=24,
        description="Number of samples to take from light programs per second",
    )

    
    use_pyro_control = BoolProperty(
        name="Export pyro (PRO)",
        description="Specifies whether the pyro program of each drone should be included in the show",
        default=False,
    )

    
    use_yaw_control = BoolProperty(
        name="Export yaw (PRO)",
        description="Specifies whether the yaw angle of each drone should be controlled during the show",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True

        layout.prop(self, "export_selected")
        layout.prop(self, "frame_range")
        layout.prop(self, "redraw")
        layout.prop(self, "output_fps")
        layout.prop(self, "light_output_fps")

        layout.separator()

        column = layout.column(align=True)
        column.prop(self, "use_pyro_control")
        column.prop(self, "use_yaw_control")

    def get_format(self) -> FileFormat:
        return FileFormat.DDSF

    def get_operator_name(self) -> str:
        return "Depence .ddsf exporter"

    def get_settings(self) -> dict[str, Any]:
        return {
            "output_fps": self.output_fps,
            "light_output_fps": self.light_output_fps,
            "use_pyro_control": self.use_pyro_control,
            "use_yaw_control": self.use_yaw_control,
        }
