from typing import Any

from bpy.props import BoolProperty, FloatProperty, StringProperty

from sbstudio.model.file_formats import FileFormat

from .base import ExportOperator

__all__ = ("DrotekExportOperator",)







class DrotekExportOperator(ExportOperator):
    

    bl_idname = "export_scene.drotek"
    bl_label = "Export Drotek format"
    bl_options = {"REGISTER"}

    
    filter_glob = StringProperty(default="*.json", options={"HIDDEN"})
    filename_ext = ".json"

    
    use_rgbw = BoolProperty(
        name="Use RGBW colors",
        default=True,
        description="Whether to convert colors to RGBW automatically during export",
    )

    
    spacing = FloatProperty(
        name="Takeoff grid spacing",
        default=2,
        description="Distance between slots in the takeoff grid.",
    )

    def get_format(self) -> FileFormat:
        return FileFormat.DROTEK

    def get_operator_name(self) -> str:
        return "Drotek exporter"

    def get_settings(self) -> dict[str, Any]:
        return {
            "spacing": self.spacing,
            "output_fps": 5,
            "light_output_fps": 5,
            "use_rgbw": self.use_rgbw,
        }
