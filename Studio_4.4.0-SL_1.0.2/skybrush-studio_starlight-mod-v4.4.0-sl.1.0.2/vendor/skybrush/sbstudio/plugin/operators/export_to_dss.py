from typing import Any

from bpy.props import IntProperty, StringProperty

from sbstudio.model.file_formats import FileFormat

from .base import ExportOperator

__all__ = ("DSSPathExportOperator", "DSSPath3ExportOperator")







class DSSPathExportOperator(ExportOperator):
    

    bl_idname = "export_scene.dss_path"
    bl_label = "Export DSS PATH"
    bl_options = {"REGISTER"}

    
    filter_glob = StringProperty(default="*.zip", options={"HIDDEN"})
    filename_ext = ".zip"

    def get_format(self) -> FileFormat:
        return FileFormat.DSS

    def get_operator_name(self) -> str:
        return "DSS PATH exporter"

    def get_settings(self) -> dict[str, Any]:
        return {}


class DSSPath3ExportOperator(ExportOperator):
    

    bl_idname = "export_scene.dss_path3"
    bl_label = "Export DSS PATH3"
    bl_options = {"REGISTER"}

    
    filter_glob = StringProperty(default="*.zip", options={"HIDDEN"})
    filename_ext = ".zip"

    
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

    def get_format(self) -> FileFormat:
        return FileFormat.DSS3

    def get_operator_name(self) -> str:
        return "DSS PATH3 exporter"

    def get_settings(self) -> dict[str, Any]:
        return {
            "output_fps": self.output_fps,
            "light_output_fps": self.light_output_fps,
        }
