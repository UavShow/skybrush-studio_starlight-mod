

from collections.abc import Iterator
from contextlib import contextmanager
from math import radians

import bmesh
import bpy
from mathutils import Matrix

from sbstudio.model.types import Coordinate3D

from .objects import create_object

__all__ = (
    "create_cone",
    "create_icosphere",
    "edit_mesh",
    "subdivide_edges",
)


def create_cone(
    center: Coordinate3D = (0, 0, 0), radius: float = 1, *, name: str | None = None
):
    
    with use_b_mesh() as bm:
        bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            cap_tris=True,
            segments=32,
            radius1=radius,
            depth=radius * 2,
            matrix=Matrix.Rotation(radians(90), 3, "Y"),
            calc_uvs=True,
        )
        obj = create_object_from_bmesh(bm, name=name or "Cone")

    obj.location = center

    return obj


def create_icosphere(
    center: Coordinate3D = (0, 0, 0), radius: float = 1, *, name: str | None = None
):
    
    with use_b_mesh() as bm:
        bmesh.ops.create_icosphere(
            bm, subdivisions=2, radius=radius, matrix=Matrix(), calc_uvs=True
        )
        obj = create_object_from_bmesh(bm, name=name or "Icosphere")

    obj.location = center
    return obj


def create_object_from_bmesh(bm, *, name: str | None = None):
    
    mesh = bpy.data.meshes.new("Mesh")
    bm.to_mesh(mesh)

    obj = create_object(name or "Object", mesh)
    mesh.name = f"{obj.name} Mesh"

    return obj


@contextmanager
def edit_mesh(obj) -> Iterator[bmesh.types.BMesh]:
    
    if isinstance(obj, bmesh.types.BMesh):
        yield obj
    elif isinstance(obj, bpy.types.Mesh):
        with use_b_mesh() as result:
            result.from_mesh(obj)
            yield result
            result.to_mesh(obj)
    else:
        with use_b_mesh() as result:
            result.from_mesh(obj.data)
            yield result
            result.to_mesh(obj.data)


@contextmanager
def use_b_mesh() -> Iterator[bmesh.types.BMesh]:
    
    result = bmesh.new()
    try:
        yield result
    finally:
        result.free()


def subdivide_edges(obj, cuts: int = 1):
    
    if cuts <= 0:
        return

    with edit_mesh(obj) as mesh:
        bmesh.ops.subdivide_edges(mesh, edges=mesh.edges, use_grid_fill=True, cuts=cuts)
