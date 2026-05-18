from collections.abc import Iterable
from typing import Any, cast

import bpy
from bpy.types import Collection, Context, Mesh, MeshVertex, Object, Scene, VertexGroup
from mathutils import Vector

from sbstudio.model.types import Coordinate3D

from .utils import with_context, with_scene

__all__ = (
    "create_object",
    "duplicate_object",
    "get_axis_aligned_bounding_box_of_object",
    "get_derived_object_after_applying_modifiers",
    "get_vertices_of_object",
    "get_vertices_of_object_in_vertex_group",
    "get_vertices_of_object_in_vertex_group_by_name",
    "link_object_to_scene",
    "object_contains_vertex",
    "remove_objects",
)


@with_scene
def create_object(name: str, data: Any = None, scene: Scene | None = None) -> Object:
    
    object = bpy.data.objects.new(name, data)
    return link_object_to_scene(object, scene=scene)


@with_scene
def duplicate_object(
    object: Object, *, name: str | None = None, scene: Scene | None = None
) -> Object:
    
    duplicate = object.copy()
    duplicate.data = object.data.copy()
    duplicate.name = name
    return link_object_to_scene(duplicate, scene=scene)


def get_vertices_of_object(object: Object):
    
    data = object.data if object else None
    return getattr(data, "vertices", [])


def get_vertices_of_object_in_vertex_group(
    object: Object, group: VertexGroup
) -> list[MeshVertex]:
    
    result: list[MeshVertex] = []
    mesh = object.data if object else None
    if mesh is not None:
        mesh = cast(Mesh, mesh)
        index = group.index
        for vertex in mesh.vertices:
            if any(g.group == index for g in vertex.groups):
                result.append(vertex)
    return result


def get_vertices_of_object_in_vertex_group_by_name(
    object: Object, name: str
) -> list[MeshVertex]:
    
    group = object.vertex_groups.get(name)
    return get_vertices_of_object_in_vertex_group(object, group) if group else []


@with_scene
def link_object_to_scene(
    object: Object, *, scene: Scene | None = None, allow_nested: bool = False
) -> Object:
    
    assert scene is not None
    parent = scene.collection
    is_collection = isinstance(object, bpy.types.Collection)
    parent = parent.children if is_collection else parent.objects

    if allow_nested:
        
        
        num_refs = scene.user_of_id(object)
        if object is scene.skybrush.settings.drone_collection:
            
            num_refs -= 1
        should_link = num_refs < 1
    else:
        
        should_link = object not in parent.values()

    if should_link:
        parent.link(object)

    return object


def object_contains_vertex(obj: Object, vertex: MeshVertex) -> bool:
    
    mesh = obj.data if obj else None
    index = vertex.index
    return mesh and len(mesh.vertices) > index and mesh.vertices[index] == vertex


def remove_objects(objects: Iterable[Object] | Collection) -> None:
    
    collection: Collection | None = None
    to_remove: Iterable[Object]

    if isinstance(objects, Collection):
        collection = objects
        to_remove = collection.objects
    else:
        to_remove = objects

    for obj in to_remove:
        bpy.data.objects.remove(obj, do_unlink=True)

    if collection:
        bpy.data.collections.remove(collection)

    """
    # Prevent a circular import with lazy imports
    from .selection import select_only

    # TODO(ntamas): it would be nicer not to change the selection
    select_only(objects, context=context)
    for obj in objects:
        obj.hide_set(False)

    result = bpy.ops.object.delete()
    if result != {"FINISHED"}:
        raise RuntimeError(f"Blender operator returned {result!r}, expected FINISHED")
    """


@with_context
def get_derived_object_after_applying_modifiers(
    obj: Object, *, context: Context | None = None
) -> Object:
    
    if obj.modifiers:
        assert context is not None
        dependency_graph = context.evaluated_depsgraph_get()
        return obj.evaluated_get(dependency_graph)
    else:
        return obj


@with_context
def get_axis_aligned_bounding_box_of_object(
    obj: Object, *, apply_modifiers: bool = True, context: Context | None = None
) -> tuple[Coordinate3D, Coordinate3D]:
    
    if apply_modifiers:
        obj = get_derived_object_after_applying_modifiers(obj, context=context)

    mat = obj.matrix_world
    world_coords = [mat @ Vector(coord) for coord in obj.bound_box]

    mins, maxs = list(world_coords[0]), list(world_coords[0])
    for coord in world_coords:
        mins[0] = min(mins[0], coord.x)
        mins[1] = min(mins[1], coord.y)
        mins[2] = min(mins[2], coord.z)
        maxs[0] = max(maxs[0], coord.x)
        maxs[1] = max(maxs[1], coord.y)
        maxs[2] = max(maxs[2], coord.z)

    return tuple(mins), tuple(maxs)
