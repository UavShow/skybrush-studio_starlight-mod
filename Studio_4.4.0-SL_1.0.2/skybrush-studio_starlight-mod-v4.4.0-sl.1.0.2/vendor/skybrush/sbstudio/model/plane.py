from dataclasses import dataclass

from .types import Coordinate3D


@dataclass(frozen=True)
class Plane:
    

    normal: Coordinate3D
    """The normal vector of the plane."""

    offset: float
    """The offset parameter of the plane equation."""

    @classmethod
    def from_points(cls, p: Coordinate3D, q: Coordinate3D, r: Coordinate3D):
        
        pq = q[0] - p[0], q[1] - p[1], q[2] - p[2]
        pr = r[0] - p[0], r[1] - p[1], r[2] - p[2]
        normal = (
            pq[1] * pr[2] - pq[2] * pr[1],
            pq[0] * pr[2] - pq[2] * pr[0],
            pq[0] * pr[1] - pq[1] * pr[0],
        )
        if all(x == 0 for x in normal):
            raise RuntimeError("The given points are collinear")

        return cls.from_normal_and_point(normal, p)

    @classmethod
    def from_normal_and_point(cls, normal: Coordinate3D, point: Coordinate3D):
        
        offset = point[0] * normal[0] + point[1] * normal[1] + point[2] * normal[2]
        return cls(normal, offset)

    def is_front(self, p: Coordinate3D) -> bool:
        
        x = self.normal[0] * p[0] + self.normal[1] * p[1] + self.normal[2] * p[2]
        return x >= self.offset
