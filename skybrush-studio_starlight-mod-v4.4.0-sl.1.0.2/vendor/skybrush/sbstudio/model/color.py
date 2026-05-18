from dataclasses import dataclass

from mathutils import Vector

__all__ = (
    "Color3D",
    "Color4D",
)


@dataclass
class Color3D:
    

    r: int
    """Red component of the color in the range [0-255]."""

    g: int
    """Green component of the color in the range [0-255]."""

    b: int
    """Blue component of the color in the range [0-255]."""

    def at_time(self, t: float, is_fade: bool = True) -> "Color4D":
        
        return Color4D(t=t, r=self.r, g=self.g, b=self.b, is_fade=is_fade)

    def as_vector(self) -> Vector:
        
        return Vector((self.r / 255, self.g / 255, self.b / 255, 1))


@dataclass
class Color4D:
    

    t: float
    """Time in [s]."""

    r: int
    """Red component of the color in the range [0-255]."""

    g: int
    """Green component of the color in the range [0-255]."""

    b: int
    """Blue component of the color in the range [0-255]."""

    is_fade: bool = True
    """Flag to specify whether we should fade here from the previous keypoint
    (True) or maintain previous color until this moment and change here
    abruptly (False)."""

    def as_vector(self) -> Vector:
        
        return Vector((self.r / 255, self.g / 255, self.b / 255, 1))
