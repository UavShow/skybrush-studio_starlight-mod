

from typing import Any

from bpy.types import ImageTexture, Texture

from sbstudio.plugin.utils.color_ramp import (
    color_ramp_as_dict,
    update_color_ramp_from_dict,
)
from sbstudio.plugin.utils.image import find_image_by_name

__all__ = (
    "texture_as_dict",
    "update_texture_from_dict",
)


def texture_as_dict(source: Texture) -> dict[str, Any]:
    
    retval = {
        "colorRamp": None,
        "useColorRamp": source.use_color_ramp,
        "imageName": None,
    }

    if isinstance(source, ImageTexture) and source.image is not None:
        
        
        
        retval["imageName"] = source.image.name
    if source.color_ramp is not None:
        retval["colorRamp"] = color_ramp_as_dict(source.color_ramp)

    return retval


def update_texture_from_dict(target: ImageTexture, data: dict[str, Any]) -> list[str]:
    
    warnings: list[str] = []

    if use_color_ramp := data.get("useColorRamp"):
        target.use_color_ramp = use_color_ramp

    if color_ramp := data.get("colorRamp"):
        update_color_ramp_from_dict(target.color_ramp, color_ramp)

    if image_name := data.get("imageName"):
        if image := find_image_by_name(image_name):
            target.image = image
        else:
            warnings.append(
                f"Could not import texture: image {image_name!r} is not part of the current file"
            )

    return warnings
