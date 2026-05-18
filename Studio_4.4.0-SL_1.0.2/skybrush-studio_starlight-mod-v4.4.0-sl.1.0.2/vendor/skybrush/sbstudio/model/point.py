from dataclasses import dataclass

from mathutils import Vector

from sbstudio.model.types import Coordinate3D

__all__ = ("Point3D", "Point4D")


@dataclass
class Point3D:
    

    
    x: float

    
    y: float

    
    z: float

    def at_time(self, t: float) -> "Point4D":
        
        return Point4D(t=t, x=self.x, y=self.y, z=self.z)

    def as_tuple(self) -> Coordinate3D:
        
        return (self.x, self.y, self.z)

    def as_vector(self) -> Vector:
        
        return Vector((self.x, self.y, self.z))

    def as_json(self) -> list[float]:
        
        return [round(value, ndigits=3) for value in [self.x, self.y, self.z]]


@dataclass
class Point4D:
    

    
    t: float

    
    x: float

    
    y: float

    
    z: float

    def as_3d(self) -> Point3D:
        
        return Point3D(x=self.x, y=self.y, z=self.z)

    def as_tuple(self) -> tuple[float, float, float, float]:
        
        return (self.t, self.x, self.y, self.z)

    def as_vector(self) -> Vector:
        
        return Vector((self.x, self.y, self.z))
