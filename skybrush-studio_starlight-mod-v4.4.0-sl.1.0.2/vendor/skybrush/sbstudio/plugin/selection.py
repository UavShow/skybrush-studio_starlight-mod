import bpy
from bpy.types import Collection, Context

from .constants import Collections
from .objects import get_vertices_of_object
from .plugin_helpers import use_mode_for_object
from .utils import with_context

__all__ = (
    "add_to_selection",
    "deselect_all",
    "ensure_vertex_select_mode_enabled",
    "get_selected_drones",
    "get_selected_objects_from_collection",
    "get_selected_vertices",
    "get_selected_vertices_grouped_by_objects",
    "has_selection",
    "remove_from_selection",
    "select_only",
)


@with_context
def deselect_all(*, context: Context | None = None):
    
    assert context is not None
    if context.mode == "EDIT_MESH":
        
        bpy.ops.mesh.select_all(action="DESELECT")
    else:
        
        for obj in context.selected_objects:
            obj.select_set(False)


@with_context
def get_selected_drones(*, context: Context | None = None):
    
    drones = Collections.find_drones(create=False)
    return (
        get_selected_objects_from_collection(drones, context=context) if drones else []
    )


@with_context
def get_selected_objects(*, context: Context | None = None):
    
    assert context is not None
    if context.mode == "OBJECT":
        return context.selected_objects
    else:
        active_object = context.active_object
        return [active_object] if active_object else []


@with_context
def get_selected_objects_from_collection(collection, *, context: Context | None = None):
    
    result = [obj for obj in collection.objects if obj.select_get()]
    selection = get_selected_objects(context=context)
    result.sort(key=selection.index)
    return result


@with_context
def get_selected_vertices(*, context: Context | None = None):
    
    assert context is not None
    if context.mode == "OBJECT":
        
        
        vertices = []
        for obj in context.selected_objects:
            vertices.extend(get_vertices_of_object(obj))

    else:
        
        
        obj = context.active_object
        with use_mode_for_object("OBJECT"):
            pass

        vertices = [v for v in get_vertices_of_object(obj) if v.select]

    return vertices


@with_context
def get_selected_vertices_grouped_by_objects(*, context: Context | None = None):
    
    assert context is not None
    if context.mode == "OBJECT":
        
        
        return {obj: get_vertices_of_object(obj) for obj in context.selected_objects}

    elif context.active_object:
        
        
        obj = context.active_object
        with use_mode_for_object("OBJECT"):
            pass

        return {obj: [v for v in get_vertices_of_object(obj) if v.select]}

    else:
        return {}


@with_context
def has_selection(*, context: Context | None = None) -> bool:
    
    assert context is not None
    if context.mode == "EDIT_MODE":
        
        
        obj = context.active_object
        with use_mode_for_object("OBJECT"):
            pass
        return any(v.select for v in get_vertices_of_object(obj))
    else:
        return len(context.selected_objects) > 0


@with_context
def select_only(objects, *, context: Context | None = None):
    
    deselect_all(context=context)
    add_to_selection(objects, context=context)


@with_context
def add_to_selection(objects, *, context: Context | None = None):
    
    assert context is not None
    _set_selected_state_of_objects(objects, True, context=context)


@with_context
def remove_from_selection(objects, *, context: Context | None = None):
    
    assert context is not None
    _set_selected_state_of_objects(objects, False, context=context)


@with_context
def ensure_vertex_select_mode_enabled(
    enabled: bool = True, *, context: Context | None = None
) -> None:
    
    assert context is not None
    msm = context.tool_settings.mesh_select_mode
    if msm[0] != bool(enabled):
        msm = list(msm)
        msm[0] = bool(enabled)
        context.tool_settings.mesh_select_mode = msm


def _set_selected_state_of_objects(objects, state, *, context: Context):
    
    if not hasattr(objects, "__iter__"):
        objects = [objects]

    queue = list(objects)
    while queue:
        item = queue.pop()
        if hasattr(item, "select_set"):
            item.select_set(state)
        elif hasattr(item, "select"):
            item.select = state
        elif isinstance(item, Collection):
            queue.extend(item.objects)
            queue.extend(item.children)
