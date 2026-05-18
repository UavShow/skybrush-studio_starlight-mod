

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

import bpy
from bpy.types import (
    Action,
    ActionChannelbag,
    ActionKeyframeStrip,
    AnimData,
    FCurve,
    Object,
)

from .utils.collections import ensure_object_exists_in_collection

__all__ = (
    "ensure_animation_data_exists_for_object",
    "ensure_f_curve_exists_for_data_path_and_index",
    "find_all_f_curves_for_data_path",
    "find_f_curve_for_data_path",
    "find_f_curve_for_data_path_and_index",
    "get_action_for_object",
    "get_animation_data_for_object",
    "iter_all_f_curves",
    "cleanup_actions_for_object",
    "clear_all_slots_from_action",
)


def ensure_animation_data_exists_for_object(
    object: Object,
    *,
    clean: bool = False,
) -> AnimData:
    
    _ensure_action_exists_for_object(object, clean=clean)

    assert object.animation_data is not None
    return object.animation_data


def _ensure_action_exists_for_object(
    object: Object,
    name: str | None = None,
    *,
    clean: bool = False,
) -> Action:
    
    action = get_action_for_object(object)
    if action is not None:
        return action

    if not object.animation_data:
        object.animation_data_create()

    action, _ = ensure_object_exists_in_collection(
        bpy.data.actions, name or _get_name_of_action_for_object(object)
    )

    if clean:
        clear_all_slots_from_action(action)

    assert object.animation_data is not None
    object.animation_data.action = action

    return action


def _get_name_of_action_for_object(object: Object) -> str:
    
    return f"{object.name} Action"


def get_action_for_object(object: Object) -> Action | None:
    
    if object and object.animation_data and object.animation_data.action:
        return object.animation_data.action


def get_animation_data_for_object(object: Object) -> AnimData | None:
    
    return object.animation_data


def _get_channelbag_from_animation_data(
    anim_data: AnimData | None,
) -> ActionChannelbag | None:
    
    if anim_data is None:
        return None

    action = anim_data.action

    if action and len(action.layers) > 0 and len(action.layers[0].strips) > 0:
        
        
        
        strip = cast("ActionKeyframeStrip", action.layers[0].strips[0])
        slot = anim_data.action_slot
        if slot is None:
            
            
            if len(action.slots) == 0:
                return None
            slot = action.slots[0]

        bag = strip.channelbag(slot)
        return bag
    else:
        
        
        
        return None


def iter_all_f_curves(anim_data: AnimData | None) -> Iterable[FCurve]:
    
    bag = _get_channelbag_from_animation_data(anim_data)
    return iter(bag.fcurves) if bag else iter(())


def _iter_all_f_curves_and_bags(
    anim_data: AnimData | None,
) -> Iterable[tuple[FCurve, ActionChannelbag]]:
    
    bag = _get_channelbag_from_animation_data(anim_data)
    return iter((curve, bag) for curve in bag.fcurves) if bag else iter(())


def find_f_curve_for_data_path(
    anim_data: AnimData | None, data_path: str
) -> FCurve | None:
    
    for curve in iter_all_f_curves(anim_data):
        if curve.data_path == data_path:
            return curve

    return None


def find_f_curve_for_data_path_and_index(
    anim_data: AnimData | None, data_path: str, index: int
) -> FCurve | None:
    
    for curve in iter_all_f_curves(anim_data):
        if curve.data_path == data_path and curve.array_index == index:
            return curve

    return None


def find_all_f_curves_for_data_path(
    anim_data: AnimData | None, data_path: str
) -> list[FCurve]:
    
    return sorted(
        [
            curve
            for curve in iter_all_f_curves(anim_data)
            if curve.data_path == data_path
        ],
        key=lambda c: c.array_index,
    )


def ensure_f_curve_exists_for_data_path_and_index(
    object: Object, *, data_path: str, index: int
) -> FCurve:
    
    action = _ensure_action_exists_for_object(object)
    return action.fcurve_ensure_for_datablock(object, data_path, index=index)


def cleanup_actions_for_object(object: Object) -> None:
    
    anim_data = get_animation_data_for_object(object)
    if not anim_data:
        return

    to_delete = []
    for curve, bag in _iter_all_f_curves_and_bags(anim_data):
        if curve.data_path:
            try:
                object.path_resolve(curve.data_path)
            except ValueError:
                to_delete.append((bag, curve))

    while to_delete:
        bag, curve = to_delete.pop()
        bag.remove(curve)


def clear_all_slots_from_action(action: Action) -> None:
    
    slots = list(action.slots)
    for slot in slots:
        action.slots.remove(slot)
