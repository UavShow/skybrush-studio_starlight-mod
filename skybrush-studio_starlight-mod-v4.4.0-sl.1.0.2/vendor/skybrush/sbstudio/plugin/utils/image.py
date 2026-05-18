

import bpy
from bpy.types import Image

from sbstudio.model.types import RGBAColor

__all__ = ["convert_from_srgb_to_linear", "find_image_by_name", "get_pixel"]


def convert_from_srgb_to_linear(color: RGBAColor) -> RGBAColor:
    
    
    
    
    r, g, b, a = color
    return (r**2.2, g**2.2, b**2.2, a)


def find_image_by_name(name: str) -> Image | None:
    
    for img in bpy.data.images:
        if img.name == name:
            return img


def get_pixel(image: Image, x: int, y: int) -> RGBAColor:
    
    width = image.size[0]
    offs = (x + y * width) * 4

    return image.pixels[offs : offs + 4]  
