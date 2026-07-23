from functools import partial
from math import ceil

import bpy
from bpy.props import FloatProperty, IntProperty
from bpy.types import Context, Object
from natsort import natsorted

from sbstudio.errors import SkybrushStudioError
from sbstudio.plugin.actions import (
    ensure_animation_data_exists_for_object,
    ensure_f_curve_exists_for_data_path_and_index,
)
from sbstudio.plugin.constants import Collections
from sbstudio.plugin.model.formation import create_formation, get_markers_from_formation
from sbstudio.plugin.model.storyboard import (
    Storyboard,
    StoryboardEntryPurpose,
    get_storyboard,
)
from sbstudio.plugin.utils.evaluator import create_position_evaluator

from .base import StoryboardOperator

__all__ = ("SingleDroneHoverTestOperator", "SingleBoxHoverTestOperator")


def _run_hover_test(
    op,
    storyboard: Storyboard,
    context: Context,
    *,
    source,
    slots,
    num_rounds: int,
    entry_name: str,
) -> tuple[float, float]:
    """Shared implementation of the hover test operators.

    Creates a storyboard entry named ``entry_name`` from the ``source``
    positions and inserts a takeoff-hover-descend-land keyframe profile for
    each drone. ``slots[i]`` is the (0-based) round in which the i-th drone
    performs the test, or ``None`` if the drone stays on the ground for the
    whole test. ``num_rounds`` is the total number of rounds.

    The operator ``op`` must provide the ``start_frame``, ``velocity``,
    ``altitude``, ``hover_duration``, ``velocity_z``, ``rth_altitude`` and
    ``interval`` properties.

    Returns:
        the duration of one cycle and the total duration, in seconds
    """
    fps = context.scene.render.fps

    # Phase durations in seconds
    ascent_duration = op.altitude / op.velocity
    descent_altitude = min(op.rth_altitude, op.altitude)
    descent_duration = (op.altitude - descent_altitude) / op.velocity_z
    land_speed = min(op.velocity_z, 0.5)
    land_duration = descent_altitude / land_speed
    cycle_duration = (
        ascent_duration
        + op.hover_duration
        + descent_duration
        + land_duration
        + op.interval
    )

    total_duration = num_rounds * cycle_duration - op.interval

    # Add a new storyboard entry for the hover test
    entry = storyboard.add_new_entry(
        formation=create_formation(entry_name, source),
        frame_start=op.start_frame,
        duration=int(ceil(total_duration * fps)),
        select=True,
        purpose=StoryboardEntryPurpose.LANDING,
        context=context,
    )
    assert entry is not None
    markers = get_markers_from_formation(entry.formation)

    # Ensure clean animation data for all markers
    for marker in markers:
        assert isinstance(marker, Object)
        ensure_animation_data_exists_for_object(marker, clean=True)

    # Generate the hover test trajectory of each drone
    for p, slot, marker in zip(source, slots, markers, strict=True):
        f_curves = []
        for i in range(3):
            f_curve = ensure_f_curve_exists_for_data_path_and_index(
                marker, data_path="location", index=i
            )
            f_curves.append(f_curve)
        insert = [
            partial(f_curve.keyframe_points.insert, options={"FAST"})
            for f_curve in f_curves
        ]

        path_points = []
        if slot is None:
            # This drone does not participate; stay on the ground
            path_points.append((0, p[0], p[1], p[2]))
            path_points.append((total_duration, p[0], p[1], p[2]))
        else:
            takeoff_time = slot * cycle_duration
            hover_end = takeoff_time + ascent_duration + op.hover_duration
            landed_time = hover_end + descent_duration + land_duration

            if takeoff_time > 0:
                # Stay on the ground until it is this drone's turn
                path_points.append((0, p[0], p[1], p[2]))
            path_points.append((takeoff_time, p[0], p[1], p[2]))
            # Ascend to the hover altitude
            path_points.append(
                (takeoff_time + ascent_duration, p[0], p[1], p[2] + op.altitude)
            )
            # Hover
            path_points.append((hover_end, p[0], p[1], p[2] + op.altitude))
            # Smart-RTH-like descent to the RTH altitude
            path_points.append(
                (hover_end + descent_duration, p[0], p[1], p[2] + descent_altitude)
            )
            # Slow landing from the RTH altitude to the ground
            path_points.append((landed_time, p[0], p[1], p[2]))
            if landed_time < total_duration:
                # Stay on the ground for the rest of the test
                path_points.append((total_duration, p[0], p[1], p[2]))

        for point in path_points:
            frame = round(op.start_frame + point[0] * fps)
            keyframes = (
                insert[0](frame, point[1]),
                insert[1](frame, point[2]),
                insert[2](frame, point[3]),
            )
            for keyframe in keyframes:
                keyframe.interpolation = "LINEAR"

        # Commit the insertions that we've made in "fast" mode
        for f_curve in f_curves:
            f_curve.update()

    # Recalculate the transition leading to the hover test formation
    bpy.ops.skybrush.recalculate_transitions(scope="TO_SELECTED")

    return cycle_duration, total_duration


class SingleDroneHoverTestOperator(StoryboardOperator):
    """Blender operator that adds a single-drone hover test sequence to the show.

    Each drone (in Drone 1, Drone 2, ... order) takes off alone to the given
    altitude, hovers for the given duration, then returns to the ground using
    a smart-RTH-like vertical descent (descend to the RTH altitude, then land
    slowly). After a user-defined interval, the next drone repeats the same
    procedure, until all drones have completed the hover test.
    """

    bl_idname = "skybrush.single_drone_hover_test"
    bl_label = "Single Drone Hover Test"
    bl_description = (
        "Take off, hover and land each drone one by one to test the drones "
        "individually after transportation, without flying the whole fleet at once"
    )
    bl_options = {"REGISTER", "UNDO"}

    only_with_valid_storyboard = True

    start_frame = IntProperty(
        name="at Frame", description="Start frame of the hover test sequence"
    )

    velocity = FloatProperty(
        name="with Velocity",
        description="Average vertical velocity during the takeoff of each drone",
        default=1.5,
        min=0.1,
        soft_min=0.1,
        soft_max=10,
        unit="VELOCITY",
    )

    altitude = FloatProperty(
        name="to Altitude",
        description="Hover altitude of each drone during the test",
        default=5,
        min=0.5,
        soft_min=1,
        soft_max=50,
        unit="LENGTH",
    )

    hover_duration = FloatProperty(
        name="Hover Duration (s)",
        description="Time each drone hovers at the test altitude before returning home",
        default=10,
        min=1,
        soft_max=120,
    )

    velocity_z = FloatProperty(
        name="Descent Velocity",
        description="Average vertical velocity while the drone descends to the RTH altitude",
        default=2,
        min=0.1,
        soft_min=0.1,
        soft_max=10,
        unit="VELOCITY",
    )

    rth_altitude = FloatProperty(
        name="RTH Altitude",
        description=(
            "Altitude of the smart RTH phase; the drone descends quickly to "
            "this altitude, then lands slowly from here to the ground"
        ),
        default=1,
        min=0.1,
        soft_max=10,
        unit="LENGTH",
    )

    interval = FloatProperty(
        name="Interval (s)",
        description=(
            "Time to wait after a drone has landed before the next drone takes off"
        ),
        default=5,
        min=0,
        soft_max=60,
    )

    @classmethod
    def poll(cls, context: Context):
        if not super().poll(context):
            return False

        drones = Collections.find_drones(create=False)
        return drones is not None and len(drones.objects) > 0

    def draw(self, context: Context):
        layout = self.layout
        layout.use_property_split = True

        layout.prop(self, "start_frame")
        layout.prop(self, "velocity")
        layout.prop(self, "altitude")
        layout.prop(self, "hover_duration")
        layout.separator()
        layout.prop(self, "velocity_z")
        layout.prop(self, "rth_altitude")
        layout.prop(self, "interval")

    def invoke(self, context: Context, event):
        self.start_frame = max(
            context.scene.frame_current, get_storyboard(context=context).frame_end
        )
        return context.window_manager.invoke_props_dialog(self)

    def execute_on_storyboard(self, storyboard: Storyboard, entries, context: Context):
        try:
            success = self._run(storyboard, context=context)
        except SkybrushStudioError:
            # These are handled nicely
            success = False
        return {"FINISHED"} if success else {"CANCELLED"}

    def _validate_start_frame(self, context: Context) -> bool:
        """Returns whether the start frame chosen by the user is valid."""
        storyboard = get_storyboard(context=context)
        last_frame = storyboard.frame_end if storyboard.last_entry is not None else None

        if last_frame is not None and self.start_frame < last_frame:
            self.report(
                {"ERROR"},
                f"Hover test must not start before the last entry "
                f"of the storyboard (frame {last_frame})",
            )
            return False

        return True

    def _run(self, storyboard: Storyboard, *, context: Context) -> bool:
        bpy.ops.skybrush.prepare()

        if not self._validate_start_frame(context):
            return False

        drones = Collections.find_drones().objects
        if not drones:
            return False

        # Sort the drones by name (Drone 1, Drone 2, ...) so that the test
        # sequence follows the drone numbering
        drones = natsorted(drones, key=lambda drone: drone.name)

        self.start_frame = max(self.start_frame, storyboard.frame_end) + 1

        # Evaluate the (ground) positions of the drones at the start frame
        with create_position_evaluator() as get_positions_of:
            source = get_positions_of(drones, frame=self.start_frame)

        num_drones = len(source)
        cycle_duration, total_duration = _run_hover_test(
            self,
            storyboard,
            context,
            source=source,
            slots=list(range(num_drones)),
            num_rounds=num_drones,
            entry_name="Single drone hover test",
        )

        self.report(
            {"INFO"},
            f"Hover test scheduled for {num_drones} drones, "
            f"{cycle_duration:.1f}s per drone, "
            f"{total_duration:.1f}s in total",
        )
        return True


class SingleBoxHoverTestOperator(StoryboardOperator):
    """Blender operator that adds a per-box hover test sequence to the show.

    Every box flies one drone at a time, simultaneously across all boxes.
    Within each box the drones take off in reading order (top-left first,
    left to right, top to bottom, viewed from above), as in the Starlight
    box takeoff order chart. Each round consists of takeoff, hover, and a
    smart-RTH-like descent and landing; a user-defined interval separates
    consecutive rounds.
    """

    bl_idname = "skybrush.single_box_hover_test"
    bl_label = "Single Box Hover Test"
    bl_description = (
        "Take off, hover and land one drone per box at a time (all boxes in "
        "parallel) to test large fleets box by box after transportation"
    )
    bl_options = {"REGISTER", "UNDO"}

    only_with_valid_storyboard = True

    start_frame = IntProperty(
        name="at Frame", description="Start frame of the hover test sequence"
    )

    velocity = FloatProperty(
        name="with Velocity",
        description="Average vertical velocity during the takeoff of each drone",
        default=1.5,
        min=0.1,
        soft_min=0.1,
        soft_max=10,
        unit="VELOCITY",
    )

    altitude = FloatProperty(
        name="to Altitude",
        description="Hover altitude of each drone during the test",
        default=5,
        min=0.5,
        soft_min=1,
        soft_max=50,
        unit="LENGTH",
    )

    hover_duration = FloatProperty(
        name="Hover Duration (s)",
        description="Time each drone hovers at the test altitude before returning home",
        default=10,
        min=1,
        soft_max=120,
    )

    velocity_z = FloatProperty(
        name="Descent Velocity",
        description="Average vertical velocity while the drone descends to the RTH altitude",
        default=2,
        min=0.1,
        soft_min=0.1,
        soft_max=10,
        unit="VELOCITY",
    )

    rth_altitude = FloatProperty(
        name="RTH Altitude",
        description=(
            "Altitude of the smart RTH phase; the drone descends quickly to "
            "this altitude, then lands slowly from here to the ground"
        ),
        default=1,
        min=0.1,
        soft_max=10,
        unit="LENGTH",
    )

    interval = FloatProperty(
        name="Interval (s)",
        description=(
            "Time to wait after a round of drones has landed before the next "
            "round takes off"
        ),
        default=5,
        min=0,
        soft_max=60,
    )

    drones_per_box = IntProperty(
        name="Drones per Box",
        description="Number of drones in each box of the takeoff grid",
        default=8,
        min=1,
        soft_max=16,
    )

    @classmethod
    def poll(cls, context: Context):
        if not super().poll(context):
            return False

        drones = Collections.find_drones(create=False)
        return drones is not None and len(drones.objects) > 0

    def draw(self, context: Context):
        layout = self.layout
        layout.use_property_split = True

        layout.prop(self, "start_frame")
        layout.prop(self, "velocity")
        layout.prop(self, "altitude")
        layout.prop(self, "hover_duration")
        layout.separator()
        layout.prop(self, "velocity_z")
        layout.prop(self, "rth_altitude")
        layout.prop(self, "interval")
        layout.separator()
        layout.prop(self, "drones_per_box")

    def invoke(self, context: Context, event):
        self.start_frame = max(
            context.scene.frame_current, get_storyboard(context=context).frame_end
        )
        return context.window_manager.invoke_props_dialog(self)

    def execute_on_storyboard(self, storyboard: Storyboard, entries, context: Context):
        try:
            success = self._run(storyboard, context=context)
        except SkybrushStudioError:
            # These are handled nicely
            success = False
        return {"FINISHED"} if success else {"CANCELLED"}

    def _validate_start_frame(self, context: Context) -> bool:
        """Returns whether the start frame chosen by the user is valid."""
        storyboard = get_storyboard(context=context)
        last_frame = storyboard.frame_end if storyboard.last_entry is not None else None

        if last_frame is not None and self.start_frame < last_frame:
            self.report(
                {"ERROR"},
                f"Hover test must not start before the last entry "
                f"of the storyboard (frame {last_frame})",
            )
            return False

        return True

    def _run(self, storyboard: Storyboard, *, context: Context) -> bool:
        bpy.ops.skybrush.prepare()

        if not self._validate_start_frame(context):
            return False

        drones = Collections.find_drones().objects
        if not drones:
            return False

        # Sort the drones by name (Drone 1, Drone 2, ...); the takeoff grid
        # creates the drones of each box consecutively in this order
        drones = natsorted(drones, key=lambda drone: drone.name)

        # Only the box array participates in this test; traditional array
        # drones (if any, in mixed mode) stay on the ground
        num_drones = len(drones)
        box_count = int(context.scene.get("sb_mixed_box_count", 0))
        if box_count <= 0 or box_count > num_drones:
            self.report(
                {"ERROR"},
                "No box array found in the takeoff grid; create a takeoff "
                "grid with a box preset first",
            )
            return False

        self.start_frame = max(self.start_frame, storyboard.frame_end) + 1

        # Evaluate the (ground) positions of the drones at the start frame
        with create_position_evaluator() as get_positions_of:
            source = get_positions_of(drones, frame=self.start_frame)

        # Assign each box drone to a round: chunk the box drones into boxes
        # of `drones_per_box` consecutive drones, then order the drones of
        # each box in reading order (top-left first, left to right, top to
        # bottom, viewed from above)
        slots: list = [None] * num_drones
        num_rounds = 0
        for chunk_start in range(0, box_count, self.drones_per_box):
            chunk = list(range(chunk_start, min(chunk_start + self.drones_per_box, box_count)))
            chunk.sort(key=lambda i: (-source[i][1], source[i][0]))
            for slot, index in enumerate(chunk):
                slots[index] = slot
            num_rounds = max(num_rounds, len(chunk))

        cycle_duration, total_duration = _run_hover_test(
            self,
            storyboard,
            context,
            source=source,
            slots=slots,
            num_rounds=num_rounds,
            entry_name="Single box hover test",
        )

        num_boxes = int(ceil(box_count / self.drones_per_box))
        self.report(
            {"INFO"},
            f"Box hover test scheduled for {box_count} drones in {num_boxes} "
            f"boxes, {num_rounds} rounds of {cycle_duration:.1f}s, "
            f"{total_duration:.1f}s in total",
        )
        return True
