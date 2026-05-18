from typing import Any

from bpy.props import StringProperty

from sbstudio.model.file_formats import FileFormat

from .base import ExportOperator

__all__ = ("LitebeeExportOperator",)







class LitebeeExportOperator(ExportOperator):
    

    bl_idname = "export_scene.litebee"
    bl_label = "Export Litebee format"
    bl_options = {"REGISTER"}

    
    filter_glob = StringProperty(default="*.bin", options={"HIDDEN"})
    filename_ext = ".bin"

    def get_format(self) -> FileFormat:
        return FileFormat.LITEBEE

    def get_operator_name(self) -> str:
        return "Litebee exporter"

    def get_settings(self) -> dict[str, Any]:
        return {}
