

from typing import Any

from bpy.props import EnumProperty, FloatProperty, StringProperty
from bpy.types import Context

from sbstudio.model.file_formats import FileFormat
from sbstudio.plugin.operators.utils import get_show_location

from .base import ExportOperator

__all__ = ("KMZExportOperator",)







class KMZExportOperator(ExportOperator):
    

    bl_idname = "export_scene.kmz"
    bl_label = "Export KMZ format"
    bl_options = {"REGISTER"}

    
    filter_glob = StringProperty(default="*.kmz", options={"HIDDEN"})
    filename_ext = ".kmz"

    
    output_fps = FloatProperty(
        name="Frame rate",
        default=4,
        description="Number of samples to take from trajectories and lights per second",
    )

    export_mode = EnumProperty(
        name="Export mode",
        description="List of supported export modes",
        items=[
            ("POINT", "Point", "Visualize drone objects as points"),
            (
                "TRAJECTORY",
                "Trajectory",
                "Visualize drone objects and their trajectories",
            ),
        ],
        default="TRAJECTORY",
    )

    def execute(self, context: Context):
        if get_show_location(context) is None:
            self.report(
                {"ERROR_INVALID_INPUT"},
                "Google Earth KMZ exporter requires a valid show location",
            )
            return {"CANCELLED"}

        return super().execute(context)

    def get_format(self) -> FileFormat:
        return FileFormat.KMZ

    def get_operator_name(self) -> str:
        return "KMZ exporter"

    def get_settings(self) -> dict[str, Any]:
        return {
            "output_fps": self.output_fps,
            "light_output_fps": self.output_fps,
            "export_mode": self.export_mode,
        }

    def invoke(self, context: Context, event):
        if get_show_location(context) is None:
            self.report(
                {"ERROR_INVALID_INPUT"},
                "Google Earth KMZ exporter requires a valid show location",
            )
            return {"CANCELLED"}

        return super().invoke(context, event)
