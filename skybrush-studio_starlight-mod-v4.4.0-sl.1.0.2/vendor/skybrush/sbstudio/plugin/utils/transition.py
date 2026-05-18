from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bpy.types import Constraint, CopyLocationConstraint, Object

from .identifiers import create_internal_id, is_internal_id

if TYPE_CHECKING:
    from sbstudio.plugin.model import StoryboardEntry


__all__ = (
    "create_transition_constraint_between",
    "find_transition_constraint_between",
    "get_id_for_formation_constraint",
    "is_transition_constraint",
    "set_constraint_name_from_storyboard_entry",
)


def get_id_for_formation_constraint(storyboard_entry: StoryboardEntry):
    
    
    
    return create_internal_id(f"Entry {storyboard_entry.id}")


def create_transition_constraint_between(
    drone: Object, storyboard_entry: StoryboardEntry
) -> CopyLocationConstraint:
    
    constraint = drone.constraints.new(type="COPY_LOCATION")
    constraint.name = get_id_for_formation_constraint(storyboard_entry)
    constraint.influence = 0

    return cast(CopyLocationConstraint, constraint)


def find_transition_constraint_between(
    drone: Object, storyboard_entry: StoryboardEntry
) -> CopyLocationConstraint | None:
    
    expected_id = get_id_for_formation_constraint(storyboard_entry)

    for constraint in drone.constraints:
        if constraint.type == "COPY_LOCATION" and constraint.name == expected_id:
            return cast(CopyLocationConstraint, constraint)

    return None


def is_transition_constraint(constraint: Constraint) -> bool:
    
    return (
        constraint
        and getattr(constraint, "type", None) == "COPY_LOCATION"
        and is_internal_id(constraint.name)
        and "[Entry " in constraint.name
    )


def set_constraint_name_from_storyboard_entry(
    constraint: Constraint, storyboard_entry: StoryboardEntry
) -> None:
    
    constraint.name = get_id_for_formation_constraint(storyboard_entry)
