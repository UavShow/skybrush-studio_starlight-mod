from bpy.types import Context

from sbstudio.model.cameras import Camera
from sbstudio.plugin.utils.evaluator import (
    get_position_of_object,
    get_quaternion_rotation_of_object,
)

__all__ = ("get_cameras_from_context",)


def get_cameras_from_context(context: Context) -> list[Camera]:
    
    cameras = [obj for obj in context.scene.objects if obj.type == "CAMERA"]

    return [
        Camera(
            name=camera.name,
            position=get_position_of_object(camera),
            orientation=get_quaternion_rotation_of_object(camera),
        )
        for camera in cameras
    ]
