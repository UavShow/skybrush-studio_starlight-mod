from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import partial
from itertools import count
from typing import TYPE_CHECKING, TypeGuard

import bpy
from bpy.types import Collection
from numpy import array, c_, dot, float64, ones, zeros
from numpy.typing import NDArray

from sbstudio.model.types import Coordinate3D
from sbstudio.plugin.constants import Collections
from sbstudio.plugin.objects import (
    get_derived_object_after_applying_modifiers,
    get_vertices_of_object_in_vertex_group_by_name,
)
from sbstudio.plugin.utils import create_object_in_collection
from sbstudio.plugin.utils.evaluator import get_position_of_object

if TYPE_CHECKING:
    from bpy.types import EmptyDisplayType, MeshVertex, Object

__all__ = (
    "add_objects_to_formation",
    "add_points_to_formation",
    "count_markers_in_formation",
    "create_formation",
    "create_marker",
    "get_markers_from_formation",
    "get_markers_and_related_objects_from_formation",
    "get_world_coordinates_of_markers_from_formation",
    "is_formation",
    "remove_formation",
)


def _get_marker_name(formation: str, index: int) -> str:
    
    return f"{formation} - {index + 1}"


def create_formation(
    name: str, points: Iterable[Coordinate3D] | None = None
) -> Collection:
    
    formation = create_object_in_collection(
        Collections.find_formations().children,
        name,
        factory=partial(bpy.data.collections.new, name),
        remover=remove_formation,
    )

    add_points_to_formation(formation, points, name=name)

    return formation


def create_marker(
    location: Coordinate3D,
    name: str,
    *,
    type: EmptyDisplayType = "PLAIN_AXES",
    size: float = 1,
    collection: Collection | None = None,
) -> Object:
    
    collection = collection or bpy.context.scene.collection
    assert collection is not None

    marker = bpy.data.objects.new(name, None)
    marker.empty_display_size = size
    marker.empty_display_type = type
    marker.location = location

    collection.objects.link(marker)

    return marker


def add_objects_to_formation(
    formation: Collection,
    objects: Iterable[Object] | None,
) -> None:
    
    if objects:
        for obj in objects:
            formation.objects.link(obj)


def add_points_to_formation(
    formation: Collection,
    points: Iterable[Coordinate3D] | None,
    *,
    name: str | None = None,
) -> list[Object]:
    
    result = []

    formation_name = name or formation.name or ""
    existing_names = {obj.name for obj in formation.objects}

    index = 0
    for index in count():
        name_candidate = _get_marker_name(formation_name, index)
        if name_candidate not in existing_names:
            break

    for point in points or []:
        while True:
            marker_name = _get_marker_name(formation_name, index)
            if marker_name in existing_names:
                index += 1
            else:
                break

        marker = create_marker(
            location=point, name=marker_name, collection=formation, size=0.5
        )
        result.append(marker)

        existing_names.add(marker_name)
        index += 1

    return result


def count_markers_in_formation(formation: Collection) -> int:
    
    result = 0

    for obj in formation.objects:
        vertex_group_name = obj.skybrush.formation_vertex_group
        if vertex_group_name:
            result += len(
                get_vertices_of_object_in_vertex_group_by_name(obj, vertex_group_name)
            )
        else:
            result += 1

    return result


def get_markers_and_related_objects_from_formation(
    formation: Collection,
) -> list[tuple[Object | MeshVertex, Object]]:
    

    
    
    
    

    result: list[tuple[Object | MeshVertex, Object]] = []

    for obj in formation.objects:
        vertex_group_name = obj.skybrush.formation_vertex_group
        if vertex_group_name:
            result.extend(
                (vertex, obj)
                for vertex in get_vertices_of_object_in_vertex_group_by_name(
                    obj, vertex_group_name
                )
            )
        else:
            result.append((obj, obj))

    return result


def get_markers_from_formation(
    formation: Collection,
) -> list[Object | MeshVertex]:
    
    result: list[Object | MeshVertex] = []

    for obj in formation.objects:
        vertex_group_name = obj.skybrush.formation_vertex_group
        if vertex_group_name:
            result.extend(
                get_vertices_of_object_in_vertex_group_by_name(obj, vertex_group_name)
            )
        else:
            result.append(obj)

    return result


def ensure_formation_consists_of_points(
    formation: Collection, points: Sequence[Coordinate3D]
) -> None:
    
    
    for child in formation.children:
        formation.children.unlink(child)  

    
    for obj in formation.objects:
        if getattr(obj, "type", None) != "EMPTY":
            if obj.users <= 1:
                bpy.data.objects.remove(obj)
            else:
                formation.objects.unlink(obj)

    
    num_empties = len(formation.objects)
    for obj, point in zip(formation.objects, points):
        obj.location = point

    
    if num_empties < len(points):
        add_points_to_formation(formation, points[num_empties:])


def get_world_coordinates_of_markers_from_formation(
    formation: Collection, *, frame: int | None = None, apply_modifiers: bool = True
) -> NDArray[float64]:
    
    
    
    

    if frame is not None:
        scene = bpy.context.scene
        current_frame = scene.frame_current
        scene.frame_set(frame)
        try:
            return get_world_coordinates_of_markers_from_formation(formation)
        finally:
            scene.frame_set(current_frame)

    vertices_by_obj: dict[Object, list[MeshVertex]] = {}

    num_rows = 0
    for obj in formation.objects:
        vertex_group_name = obj.skybrush.formation_vertex_group
        if vertex_group_name:
            
            
            
            if apply_modifiers:
                derived_object = get_derived_object_after_applying_modifiers(obj)
            else:
                derived_object = obj
            vertices = get_vertices_of_object_in_vertex_group_by_name(
                derived_object, vertex_group_name
            )
            vertices_by_obj[obj] = vertices
            num_rows += len(vertices)
        else:
            num_rows += 1

    result = zeros((num_rows, 3))
    row_index = 0

    for obj in formation.objects:
        vertices = vertices_by_obj.get(obj)
        if vertices is not None:
            num_vertices = len(vertices)
            mw = array(obj.matrix_world)
            if num_vertices:
                coords = c_[array([v.co for v in vertices]), ones(num_vertices)]
                result[row_index : (row_index + num_vertices), :] = dot(mw, coords.T)[
                    0:3
                ].T
            row_index += num_vertices
        else:
            result[row_index, :] = get_position_of_object(obj)
            row_index += 1

    return result


def is_formation(object: Object) -> TypeGuard[Collection]:
    
    if not isinstance(object, Collection):
        return False

    
    
    formations = Collections.find_formations(create=False)
    return formations is not None and object in formations.children.values()


def remove_formation(formation: Collection) -> None:
    
    formations = Collections.find_formations(create=False)
    if not formations:
        return

    formations.children.unlink(formation)

    for obj in formation.objects:
        if obj.users <= 1:
            bpy.data.objects.remove(obj)

    bpy.data.collections.remove(formation)
