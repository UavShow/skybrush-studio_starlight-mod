

from typing import Any

from bpy.props import FloatProperty, StringProperty

from sbstudio.model.file_formats import FileFormat

from .base import ExportOperator

__all__ = ("SkybrushCSVExportOperator",)







class SkybrushCSVExportOperator(ExportOperator):
    

    bl_idname = "export_scene.skybrush_csv"
    bl_label = "Export Skybrush CSV"
    bl_options = {"REGISTER"}

    
    filter_glob = StringProperty(default="*.zip", options={"HIDDEN"})
    filename_ext = ".zip"

    
    output_fps = FloatProperty(
        name="Frame rate",
        default=4,
        description="Number of samples to take from trajectories and lights per second",
    )

    def get_format(self) -> FileFormat:
        return FileFormat.CSV

    def get_operator_name(self) -> str:
        return "CSV exporter"

    def get_settings(self) -> dict[str, Any]:
        return {
            "output_fps": self.output_fps,
            "light_output_fps": self.output_fps,
        }
