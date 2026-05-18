from random import shuffle

import bpy
from bpy.props import EnumProperty
from bpy.types import Collection, Context
from natsort import index_natsorted, order_by_index
from numpy import array, logical_or
from numpy.linalg import norm

from sbstudio.plugin.model.safety_check import get_proximity_warning_threshold
from sbstudio.plugin.utils.collections import sort_collection
from sbstudio.plugin.utils.evaluator import create_position_evaluator

from .base import FormationOperator

__all__ = ("ReorderFormationMarkersOperator",)


class ReorderFormationMarkersOperator(FormationOperator):
    

    bl_idname = "skybrush.reorder_formation_markers"
    bl_label = "Reorder Formation Markers"
    bl_description = "Re-orders individual markers within a formation"
    

    type = EnumProperty(
        items=[
            ("NAME", "Sort by name", "", 1),
            ("SHUFFLE", "Shuffle", "", 2),
            ("REVERSE", "Reverse", "", 3),
            ("X", "Sort by X coordinate", "", 4),
            ("Y", "Sort by Y coordinate", "", 5),
            ("Z", "Sort by Z coordinate", "", 6),
            ("EVERY_2", "Every 2nd", "", 7),
            ("EVERY_3", "Every 3rd", "", 8),
            ("EVERY_4", "Every 4th", "", 9),
            ("ENSURE_SAFETY_DISTANCE", "Ensure safety distance", "", 10),
        ],
        name="Type",
        description="Reordering to perform on the formation",
        default="NAME",
    )

    def execute_on_formation(self, formation: Collection | None, context: Context):
        assert formation is not None
        
        
        
        

        if len(formation.children) > 0:
            self.report({"ERROR"}, "Formation must not contain sub-collections")
            return {"CANCELLED"}

        markers = formation.objects
        func = getattr(self, f"_execute_on_formation_{self.type}", None)
        if callable(func):
            index_vector: list[int] = func(markers, context)
            reversed_mapping = {
                markers[marker_index]: slot_index
                for slot_index, marker_index in enumerate(index_vector)
            }
            bpy.ops.ed.undo_push()
            sort_collection(markers, reversed_mapping.__getitem__)
            self.report({"INFO"}, "Formation markers reordered")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, f"{self.type} method not implemented yet")
            return {"CANCELLED"}

    def _execute_on_formation_NAME(self, markers, context) -> list[int]:
        
        names = [str(getattr(marker, "name", "")) for marker in markers]
        index = index_natsorted(names)
        return order_by_index(list(range(len(markers))), index)  

    def _execute_on_formation_SHUFFLE(self, markers, context) -> list[int]:
        
        mapping = list(range(len(markers)))
        shuffle(mapping)
        return mapping

    def _execute_on_formation_REVERSE(self, markers, context) -> list[int]:
        
        return list(reversed(range(len(markers))))

    def _execute_on_formation_X(self, markers, context) -> list[int]:
        
        return self._sort_by_axis(markers, axis=0)

    def _execute_on_formation_Y(self, markers, context) -> list[int]:
        
        return self._sort_by_axis(markers, axis=1)

    def _execute_on_formation_Z(self, markers, context) -> list[int]:
        
        return self._sort_by_axis(markers, axis=2)

    def _execute_on_formation_EVERY_2(self, markers, context) -> list[int]:
        
        return self._sweep(markers, step=2)

    def _execute_on_formation_EVERY_3(self, markers, context) -> list[int]:
        
        return self._sweep(markers, step=3)

    def _execute_on_formation_EVERY_4(self, markers, context) -> list[int]:
        
        return self._sweep(markers, step=4)

    def _execute_on_formation_ENSURE_SAFETY_DISTANCE(
        self, markers, context
    ) -> list[int]:
        
        num_markers = len(markers)
        if not num_markers:
            return []

        with create_position_evaluator() as get_positions_of:
            coords = array(get_positions_of(markers))

        queue: list[int] = list(range(num_markers))
        masked = array([False] * num_markers, dtype=bool)
        skipped: list[int] = []
        result: list[int] = []

        dist_threshold: float = get_proximity_warning_threshold(context)

        while queue:
            
            masked.fill(False)

            for marker_index in queue:
                if masked[marker_index]:
                    
                    
                    skipped.append(marker_index)
                else:
                    
                    
                    closer = (
                        norm(coords - coords[marker_index], axis=1) < dist_threshold
                    )
                    closer[marker_index] = False
                    logical_or(masked, closer, out=masked)
                    result.append(marker_index)

            queue.clear()
            if skipped:
                queue.extend(skipped)
                skipped.clear()

        return result

    @staticmethod
    def _sort_by_axis(markers, *, axis: int) -> list[int]:
        
        with create_position_evaluator() as get_positions_of:
            coords = get_positions_of(markers)

        def key_func(x: int):
            return coords[x][axis]

        return sorted(range(len(markers)), key=key_func)

    @staticmethod
    def _sweep(markers, *, step: int) -> list[int]:
        
        num_markers = len(markers)
        if not num_markers or step < 2:
            return markers
        else:
            return sum(
                (list(range(start, num_markers, step)) for start in range(step)), []
            )
