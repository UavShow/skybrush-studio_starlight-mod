from __future__ import annotations

from collections.abc import Iterable, Sequence
from operator import attrgetter
from typing import Self

from sbstudio.utils import simplify_path

from .color import Color4D

__all__ = ("LightProgram",)


def _simplify_color_distance_func(
    keypoints: Iterable[Color4D], start: Color4D, end: Color4D
):
    
    timespan = end.t - start.t

    result: list[float] = []

    for point in keypoints:
        ratio = (point.t - start.t) / timespan if timespan > 0 else 0.5
        interp = (
            start.r + ratio * (end.r - start.r),
            start.g + ratio * (end.g - start.g),
            start.b + ratio * (end.b - start.b),
        )

        diff = max(
            abs(interp[0] - point.r),
            abs(interp[1] - point.g),
            abs(interp[2] - point.b),
        )
        result.append(diff)

    return result


def _simplify_color_eq_func(p1: Color4D, p2: Color4D):
    
    return p1.r == p2.r and p1.g == p2.g and p1.b == p2.b


class LightProgram:
    

    def __init__(self, colors: Sequence[Color4D] | None = None):
        self.colors = sorted(colors, key=attrgetter("t")) if colors is not None else []

    def append(self, color: Color4D) -> None:
        
        if self.colors and self.colors[-1].t > color.t:
            raise ValueError(
                "New color must come after existing light keyframe in time"
            )
        self.colors.append(color)

    def as_dict(self, ndigits: int = 3):
        
        return {
            "data": [
                [
                    round(color.t, ndigits=ndigits),
                    [int(color.r), int(color.g), int(color.b)],
                    1 if color.is_fade else 0,
                ]
                for color in self.colors
            ],
            "version": 1,
        }

    def shift_time_in_place(self, delta: float) -> Self:
        
        for keyframe in self.colors:
            keyframe.t += delta
        return self

    def simplify(self) -> LightProgram:
        
        new_items = simplify_path(
            list(self.colors),
            eps=4,
            distance_func=_simplify_color_distance_func,
            eq_func=_simplify_color_eq_func,
        )

        return LightProgram(new_items)
