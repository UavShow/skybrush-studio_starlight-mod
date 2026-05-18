

from __future__ import annotations

from dataclasses import dataclass

from sbstudio.model.types import Coordinate3D, Quaternion

__all__ = ("Camera",)


@dataclass
class Camera:
    

    name: str
    """The name of the camera."""

    position: Coordinate3D
    """The position of the camera in 3D space."""

    orientation: Quaternion
    """The orientation of the camera using Blender quaternions."""

    def as_dict(self, ndigits: int = 3):
        
        result = {
            "name": self.name,
            "type": "perspective",
            "position": [round(value, ndigits=ndigits) for value in self.position],
            "orientation": [
                round(value, ndigits=ndigits) for value in self.orientation
            ],
        }

        return result
