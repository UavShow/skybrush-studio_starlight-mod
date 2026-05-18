from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bpy.types import Area, SpaceView3D

from .utils import with_screen

__all__ = (
    "find_all_3d_views",
    "find_all_3d_views_and_their_areas",
    "find_one_3d_view",
    "find_one_3d_view_and_its_area",
)


@with_screen
def find_all_3d_views(screen: str | None = None) -> Iterable[SpaceView3D]:
    
    for space, _area in _find_all_3d_views_and_their_areas(screen):
        yield space


@with_screen
def find_all_3d_views_and_their_areas(
    screen: str | None = None,
) -> Iterable[tuple[SpaceView3D, Area]]:
    
    
    return _find_all_3d_views_and_their_areas(screen)


def _find_all_3d_views_and_their_areas(
    screen: str | None = None,
) -> Iterable[tuple[SpaceView3D, Area]]:
    for area in screen.areas:  
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    yield space, area


@with_screen
def find_one_3d_view(screen: str | None = None) -> SpaceView3D | None:
    
    return find_one_3d_view_and_its_area(screen)[0]


@with_screen
def find_one_3d_view_and_its_area(
    screen: str | None = None,
) -> tuple[SpaceView3D | None, Area | None]:
    
    for area in screen.areas:  
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    return space, area
    return None, None
