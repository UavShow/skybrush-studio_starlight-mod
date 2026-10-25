import json
from collections.abc import Sequence
from functools import partial
from math import ceil, sqrt, isfinite
from time import monotonic, perf_counter
from types import SimpleNamespace
from mathutils import Vector

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import Context, Object
from bpy.app.translations import pgettext_iface

from sbstudio.errors import SkybrushStudioError
from sbstudio.model.types import Coordinate3D
from sbstudio.plugin.actions import (
    ensure_animation_data_exists_for_object,
    ensure_f_curve_exists_for_data_path_and_index,
    iter_all_f_curves,
)
from sbstudio.plugin.api import call_api_from_blender_operator
from sbstudio.plugin.constants import Collections
from sbstudio.plugin.model.formation import (
    create_formation,
    get_markers_from_formation,
    get_world_coordinates_of_markers_from_formation,
)
from sbstudio.plugin.model.safety_check import get_proximity_warning_threshold
from sbstudio.plugin.model.storyboard import (
    Storyboard,
    StoryboardEntryPurpose,
    get_storyboard,
)
from sbstudio.plugin.utils.evaluator import create_position_evaluator
from sbstudio.plugin.operators.rea_return_core import (
    AlgorithmNotReconstructed,
    BoidState,
    FlightLimits,
    iter_simulate_return,
    simulate_return,
)

from .base import StoryboardOperator
from .takeoff import create_helper_formation_for_takeoff_and_landing

__all__ = ("ReturnToHomeOperator",)

_ENHANCED_CONTEXT = "EnhancedRTH"
_ENHANCED_DESCENT_RAMP_SECONDS = 2.0
_ENHANCED_PROGRESS_CHUNK_SIZE = 128
_ENHANCED_PROGRESS_HEARTBEAT_SECONDS = 2.0
_ENHANCED_PROGRESS_PERCENT_STEP = 25


def _tr(message):
    return pgettext_iface(message, _ENHANCED_CONTEXT)


def _enhanced_float(**kwargs):
    kwargs.setdefault("precision", 2)
    return FloatProperty(translation_context=_ENHANCED_CONTEXT, **kwargs)


def is_smart_rth_enabled_globally() -> bool:


    return True


def use_custom_spacing_updated(self, context: Context):

    if not self.use_custom_spacing:
        self.spacing = get_proximity_warning_threshold(context)


def smart_rth_updated(self, context: Context):
    if not self.use_smart_rth:
        self.to_aerial_grid = False
    else:
        self.use_enhanced_return_to_takeoff_grid = False


def enhanced_return_updated(self, context: Context):
    if self.use_enhanced_return_to_takeoff_grid:
        self.use_smart_rth = False
        self.to_aerial_grid = False
        self.use_custom_spacing = True


def aerial_grid_updated(self, context: Context):
    if self.to_aerial_grid:
        self.use_enhanced_return_to_takeoff_grid = False


class ReturnToHomeOperator(StoryboardOperator):


    bl_idname = "skybrush.rth"
    bl_label = "Return Drones to Home Positions"
    bl_description = "Add a return-to-home maneuver to all the drones"
    bl_options = {"REGISTER", "UNDO"}

    only_with_valid_storyboard = True

    start_frame = IntProperty(
        name="at Frame", description="Start frame of the return-to-home maneuver"
    )

    velocity = FloatProperty(
        name="with Velocity",
        description="Average horizontal velocity during the return-to-home maneuver",
        default=4.5,
        min=0.1,
        soft_min=0.1,
        soft_max=10,
        unit="VELOCITY",
    )

    velocity_z = FloatProperty(
        name="with Velocity Z",
        description="Average vertical velocity during the return-to-home maneuver",
        default=2,
        min=0.1,
        soft_min=0.1,
        soft_max=10,
        unit="VELOCITY",
    )

    altitude = FloatProperty(
        name="to Altitude",
        description="Altitude to return-to-home to",
        default=30,
        soft_min=-50,
        soft_max=50,
        unit="LENGTH",
    )

    use_custom_spacing = BoolProperty(
        name="Use custom spacing",
        default=True,
        description="When checked, a custom spacing can be given instead of the default proximity warning threshold",
        update=use_custom_spacing_updated,
    )

    spacing = FloatProperty(
        name="Spacing",
        description="Grid spacing for RTH or minimum distance for smart RTH",
        default=1.6,
        min=0.1,
        soft_max=50,
        unit="LENGTH",
    )

    altitude_shift = FloatProperty(
        name="Layer height",
        description=(
            "Specifies the difference between altitudes of landing layers "
            "for multi-phase landings when multiple drones occupy the same "
            "slot within safety distance"
        ),
        default=7,
        soft_min=0,
        soft_max=50,
        unit="LENGTH",
    )

    use_smart_rth = BoolProperty(
        name="Use smart RTH (PRO)",
        description=(
            "Enable the smart return to home function that ensures that "
            "all drones return to their own home position with an optimal "
            "collision free smart transition"
        ),
        default=False,
        update=smart_rth_updated,
    )

    to_aerial_grid = BoolProperty(
        name="Return to aerial grid (PRO)",
        description=(
            "If enabled, drones will use a special planner to return to an "
            "aerial grid above home and will not land automatically afterwards. "
            "If disabled, drones will use the standard smart RTH algorithm and "
            "finish the procedure with landing to the desired common altitude"
        ),
        default=False,
        update=aerial_grid_updated,
    )

    use_enhanced_return_to_takeoff_grid = BoolProperty(
        name="Return to Aerial Grid (Direct)",
        description="Return to each drone's takeoff XY position with collision avoidance, forming an aerial formation at the configured altitude and layer height",
        translation_context=_ENHANCED_CONTEXT,
        default=True,
        update=enhanced_return_updated,
    )

    enhanced_velocity = _enhanced_float(
        name="Total speed", description="Maximum three-dimensional speed during enhanced return",
        default=5.0, min=0.01, soft_max=10.0, unit="VELOCITY",
    )
    enhanced_velocity_up = _enhanced_float(
        name="Up", description="Maximum upward speed during enhanced return",
        default=3.0, min=0.01, soft_max=10.0, unit="VELOCITY",
    )
    enhanced_velocity_down = _enhanced_float(
        name="Down", description="Maximum downward speed during enhanced return",
        default=2.0, min=0.01, soft_max=10.0, unit="VELOCITY",
    )
    enhanced_final_altitude = _enhanced_float(
        name="Return at this altitude", description="Height of the lowest drone formation layer above ground",
        default=5.0, min=0.0, unit="LENGTH",
    )
    enhanced_descent_speed = _enhanced_float(
        name="Descent speed", description="Maximum formation descent speed after all drones reach the grid",
        default=2.0, min=0.01, unit="VELOCITY",
    )


    rth_group = EnumProperty(
        name="Return Group",
        description=(
            "Select which drone group should return to home at this time. "
            "Drones NOT in the selected group will keep their current position. "
            "Only available with smart RTH. Run this operator multiple times "
            "(at different start frames, with different groups) to control "
            "each group's return independently."
        ),
        items=[
            ("ALL", "All drones", "All drones return together (default)", 1),
            ("BOX", "Box array only", "Only BOX drones return; TRAD drones keep position", 2),
            ("TRAD", "Traditional array only", "Only TRAD drones return; BOX drones keep position", 3),
        ],
        default="ALL",
        options=set(),
    )

    scale_down_drones = BoolProperty(
        name="Scale Down Drones",
        default=True,
        description="Scale the drones back to 0.15 m at the end of the return-to-home maneuver",
    )

    show_progress = BoolProperty(
        name="Show progress",
        description="Display the direct return calculation progress in Blender",
        translation_context=_ENHANCED_CONTEXT,
        default=True,
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
        enhanced = self.use_enhanced_return_to_takeoff_grid
        layout.ui_units_x = 15
        layout.use_property_decorate = False

        def field(identifier, title=None):
            if not enhanced:
                layout.prop(self, identifier)
                return
            split = layout.split(factor=0.40, align=True)
            label = split.row()
            label.alignment = "RIGHT"
            if title is None:
                native_titles = {
                    "start_frame": "at Frame",
                    "velocity": "with Velocity",
                    "altitude": "to Altitude",
                    "altitude_shift": "Layer height",
                }
                enhanced_titles = {
                    "enhanced_velocity": "Total speed",
                    "enhanced_descent_speed": "Descent speed",
                    "enhanced_final_altitude": "Return at this altitude",
                }
                if identifier in native_titles:
                    label.label(text=native_titles[identifier])
                else:
                    label.label(text=_tr(enhanced_titles[identifier]), translate=False)
            else:
                label.label(text=_tr(title), translate=False)
            value = split.row(align=True)
            value.use_property_split = False
            value.prop(self, identifier, text="")

        use_smart_rth = self.use_smart_rth and not enhanced
        to_aerial_grid = use_smart_rth and self.to_aerial_grid
        field("start_frame")
        if use_smart_rth:
            row = layout.row()
            row.prop(self, "velocity")
            row.separator()
            row.label(text="XY")
            row.separator()
            row.prop(self, "velocity_z", text="")
            row.separator()
            row.label(text="Z")
        else:
            field("velocity")
        field("altitude", "Assembly altitude" if enhanced else None)
        if not use_smart_rth or to_aerial_grid:
            if enhanced:
                field("altitude_shift")
            else:
                row = layout.row()
                row.prop(self, "altitude_shift")
            if not enhanced and self.altitude_shift < self.spacing:
                row.alert = True
                row.label(text="", icon="ERROR")
        row = layout.row(heading="Spacing")
        row.prop(self, "use_custom_spacing", text="")
        row = row.row()
        row.prop(self, "spacing", text="")
        row.enabled = self.use_custom_spacing
        if self.spacing < get_proximity_warning_threshold(context):
            row.alert = True
            row.label(text="", icon="ERROR")
        layout.prop(self, "use_enhanced_return_to_takeoff_grid")
        if is_smart_rth_enabled_globally():
            layout.prop(self, "use_smart_rth")
            if use_smart_rth:
                layout.prop(self, "to_aerial_grid")

                layout.separator()
                row = layout.row()
                row.prop(self, "rth_group")
        if enhanced:
            row = layout.row(align=True)
            row.prop(self, "scale_down_drones")
            row.prop(self, "show_progress")
        else:
            layout.prop(self, "scale_down_drones")
        if enhanced:
            layout.separator(factor=0.5)
            field("enhanced_velocity")
            field("enhanced_velocity_up", "Upward speed")
            field("enhanced_velocity_down", "Downward speed")
            field("enhanced_descent_speed")
            field("enhanced_final_altitude")

    def check(self, context):
        return True

    def invoke(self, context, event):
        self.start_frame = max(
            context.scene.frame_current, get_storyboard(context=context).frame_end
        )
        if not self.use_custom_spacing:
            self.spacing = get_proximity_warning_threshold(context)

        return context.window_manager.invoke_props_dialog(self, width=300)

    def execute_on_storyboard(self, storyboard: Storyboard, entries, context: Context):
        try:
            success = self._run(storyboard, context=context)
        except SkybrushStudioError:

            success = False
        if getattr(self, "_enhanced_job", None) is not None:
            return {"RUNNING_MODAL"}
        return {"FINISHED"} if success else {"CANCELLED"}

    def _should_use_smart_rth(self) -> bool:
        return (
            self.use_smart_rth or self.use_enhanced_return_to_takeoff_grid
        ) and is_smart_rth_enabled_globally()

    def _should_return_to_aerial_grid(self) -> bool:
        return self._should_use_smart_rth() and self.to_aerial_grid

    def _run(self, storyboard: Storyboard, *, context: Context) -> bool:
        bpy.ops.skybrush.prepare()
        if self.use_enhanced_return_to_takeoff_grid and not self.use_custom_spacing:
            self.spacing = get_proximity_warning_threshold(context)

        if not self._validate_start_frame(context):
            return False

        drones = Collections.find_drones().objects
        if not drones:
            return False

        use_smart_rth = self._should_use_smart_rth()
        to_aerial_grid = self._should_return_to_aerial_grid()
        self.start_frame = max(self.start_frame, storyboard.frame_end) + (
            1 if use_smart_rth else 0
        )

        with create_position_evaluator() as get_positions_of:
            source = get_positions_of(drones, frame=self.start_frame)

        first_frame = storyboard.frame_start
        if self.use_enhanced_return_to_takeoff_grid:
            try:
                target = self._get_takeoff_grid_targets(storyboard, drones)
            except (AlgorithmNotReconstructed, ValueError) as ex:
                self.report({"ERROR"}, str(ex))
                return False
        else:
            _, target, _ = create_helper_formation_for_takeoff_and_landing(
                drones,
                frame=first_frame,
                base_altitude=self.altitude,
                layer_height=0
                if (use_smart_rth and not to_aerial_grid)
                else self.altitude_shift,
                min_distance=self.spacing,
                flatten_source=to_aerial_grid,
                operator=self,
            )

        if self.use_enhanced_return_to_takeoff_grid:
            result = self._run_enhanced_return(
                storyboard, source=source, target=target, drones=drones,
                context=context,
            )
        elif use_smart_rth and self.rth_group != "ALL":
            result = self._run_smart_rth_for_group(
                storyboard, source=source, target=target, context=context,
                group=self.rth_group,
            )
        elif use_smart_rth:
            result = self._run_smart_rth(
                storyboard, source=source, target=target, context=context,
            )
        else:
            result = self._run_base_rth(
                storyboard, source=source, target=target, context=context,
            )

        if result is None and getattr(self, "_enhanced_job", None) is not None:
            return None

        return self._postprocess_run(result, storyboard, drones, context)

    def _postprocess_run(self, result, storyboard, drones, context):
        if result:
            if self.use_enhanced_return_to_takeoff_grid:
                # Reuse only local constraint binding. The operator wrapper
                # checks the online API even for MANUAL identity mappings.
                from .recalculate_transitions import RecalculationTask, recalculate_transitions
                ordered_entries = list(storyboard.entries)
                task = RecalculationTask.for_entry_by_index(ordered_entries, len(ordered_entries) - 1)
                recalculate_transitions([task], start_of_scene=min(context.scene.frame_start, storyboard.frame_start))
                bpy.ops.skybrush.update_time_markers_from_storyboard()
            else:
                bpy.ops.skybrush.recalculate_transitions(scope="TO_SELECTED")

        if (
            result
            and self.scale_down_drones
            and not self._should_return_to_aerial_grid()
        ):
            last_entry = storyboard.last_entry
            if last_entry is not None:
                end_of_rth = last_entry.frame_end
                self._apply_drone_size_keyframes(
                    drones,
                    self.start_frame,
                    end_of_rth,
                    start_small=False,
                    end_only=self.use_enhanced_return_to_takeoff_grid,
                )

        if result and self.use_enhanced_return_to_takeoff_grid:
            context.scene.frame_start = 1
            context.scene.frame_end = storyboard.last_entry.frame_end
            if context.scene.use_preview_range:
                context.scene.frame_preview_start = 1
                context.scene.frame_preview_end = storyboard.last_entry.frame_end
        return result

    def _get_takeoff_grid_targets(self, storyboard, drones):
        """Read the final Takeoff formation as ordered per-drone home positions."""
        from sbstudio.plugin.model.formation import count_markers_in_formation

        candidates = [
            entry for entry in storyboard.entries
            if entry.purpose == StoryboardEntryPurpose.TAKEOFF.name
            and entry.formation is not None
            and count_markers_in_formation(entry.formation) == len(drones)
        ]
        if not candidates:
            raise AlgorithmNotReconstructed(
                _tr("No matching Takeoff formation. Create the takeoff grid and takeoff storyboard first.")
            )

        takeoff_entry = max(
            candidates, key=lambda item: (item.frame_start, item.frame_end)
        )
        positions = get_world_coordinates_of_markers_from_formation(
            takeoff_entry.formation, frame=takeoff_entry.frame_end
        )
        if len(positions) != len(drones):
            raise AlgorithmNotReconstructed(
                _tr("Takeoff has %d positions but the scene contains %d drones.")
                % (len(positions), len(drones))
            )
        try:
            mapping = json.loads(takeoff_entry.mapping)
        except (TypeError, ValueError):
            mapping = None
        if (mapping is None or len(mapping) != len(drones)
                or any(type(index) is not int for index in mapping)
                or sorted(mapping) != list(range(len(positions)))):
            raise AlgorithmNotReconstructed(
                _tr("Takeoff has no complete one-to-one mapping. Recalculate its storyboard transition first.")
            )
        ordered = [tuple(float(c) for c in positions[index]) for index in mapping]
        # Rebuild a coordinate copy only. Takeoff markers, mappings and actions
        # are never written to by the enhanced return planner.
        levels = []
        for z in sorted(point[2] for point in ordered):
            if not levels or abs(z - levels[-1]) > 0.01:
                levels.append(z)
        return [
            (point[0], point[1], float(self.altitude) +
             min(range(len(levels)), key=lambda i: abs(point[2]-levels[i])) *
             float(self.altitude_shift))
            for point in ordered
        ]

    def _run_enhanced_return(self, storyboard, *, source, target, drones, context):
        """Create a storyboard formation animated along REA return tracks."""
        acceleration = float(context.scene.skybrush.settings.max_acceleration)
        if not isfinite(acceleration) or acceleration <= 0:
            self.report({"ERROR"}, _tr("Preferred acceleration must be greater than zero."))
            return False
        fps = context.scene.render.fps / max(context.scene.render.fps_base, 1.0e-8)
        limits_source = SimpleNamespace(
            max_velocity=float(self.enhanced_velocity),
            max_horizontal_velocity=float(self.velocity),
            max_vertical_up_velocity=float(self.enhanced_velocity_up),
            max_vertical_down_velocity=float(self.enhanced_velocity_down),
            max_x_acceleration=acceleration,
            max_y_acceleration=acceleration,
            max_z_acceleration=acceleration,
            min_distance=float(self.spacing),
        )
        limits = FlightLimits.from_scene_properties(limits_source, fps)
        if self.enhanced_final_altitude > self.altitude:
            self.report({"ERROR"}, _tr("RTH altitude must not exceed grid altitude."))
            return False
        if limits.max_velocity <= 0.0 or limits.max_acceleration <= 0.0:
            self.report({"ERROR"}, _tr("Return speed and at least one acceleration must be greater than zero."))
            return False

        if not all(isfinite(float(c)) for point in (*source, *target) for c in point):
            self.report({"ERROR"}, _tr("Drones or Takeoff contain invalid coordinates."))
            return False
        states = [
            BoidState.at(drone.name, origin, destination, limits.max_velocity)
            for drone, origin, destination in zip(drones, source, target, strict=True)
        ]
        if self.show_progress and context.window is not None:
            simulation = iter_simulate_return(
                states, limits, avoid_collision=True, start_frame=int(self.start_frame),
                # Use the steering solver with the user's nominal separation.
                # Do not post-project paths onto an additional hard distance floor.
                enforce_min_distance=False,
                chunk_size=min(_ENHANCED_PROGRESS_CHUNK_SIZE, len(drones)),
            )
            window_manager = context.window_manager
            self._enhanced_job = {
                "stage": "simulation",
                "iterator": simulation,
                "storyboard": storyboard,
                "source": source,
                "target": target,
                "drones": drones,
                "limits": limits,
                "fps": fps,
                "acceleration": acceleration,
                "window_manager": window_manager,
                "area": context.area,
                "last_header_update": 0.0,
                "latest_progress": (0, 0, len(drones)),
            }
            window_manager.progress_begin(0, 100)
            self._enhanced_job["timer"] = window_manager.event_timer_add(
                0.01, window=context.window
            )
            window_manager.modal_handler_add(self)
            self._update_enhanced_progress(context, force=True)
            return None

        try:
            # The comparison mode reproduces the old synchronous behavior:
            # one iterator hand-off per frame, with no modal UI progress work.
            tracks = simulate_return(
                states, limits, avoid_collision=True, start_frame=int(self.start_frame),
                enforce_min_distance=False, chunk_size=len(drones),
            )
        except AlgorithmNotReconstructed as ex:
            self.report({"ERROR"}, str(ex))
            return False

        writer = self._write_enhanced_return(
            storyboard, tracks, source, target, drones, limits, fps,
            acceleration, context, report_progress=False,
        )
        for _ in writer:
            pass
        return True

    def _write_enhanced_return(
        self, storyboard, tracks, source, target, drones, limits, fps, acceleration,
        context, *, report_progress=True,
    ):
        tracks, arrival_index, descent_start_index, descent_index = yield from self._append_grid_descent(
            tracks, drones, target, limits, report_progress=report_progress,
        )

        base_name = _tr("Return to Aerial Grid (Direct)")
        formation_name = base_name
        suffix = 1
        while bpy.data.collections.get(formation_name) is not None:
            formation_name = "%s.%03d" % (base_name, suffix)
            suffix += 1
        formation = create_formation(
            formation_name,
            [tuple(float(component) for component in point) for point in source],
        )
        entry = storyboard.add_new_entry(
            name=formation.name,
            formation=formation,
            frame_start=int(self.start_frame),
            duration=descent_index + 2,
            select=True,
            purpose=StoryboardEntryPurpose.LANDING,
            context=context,
        )
        # Tracks are built in drone collection order. Manual mapping preserves
        # identity and uses Studio's local constraint binding, without matching API.
        entry.transition_type = "MANUAL"
        entry.transition_schedule = "SYNCHRONIZED"
        entry.update_mapping(list(range(len(drones))))
        formation["enhanced_rth_core"] = "Enhanced RTH 1.6.0 (Studio preferred acceleration)"
        formation["grid_arrival_frame"] = int(self.start_frame) + arrival_index
        formation["grid_arrival_offset"] = arrival_index
        formation["descent_start_frame"] = int(self.start_frame) + descent_start_index
        formation["hover_frames"] = descent_start_index - arrival_index
        formation["descent_end_frame"] = int(self.start_frame) + descent_index
        formation["grid_altitude"] = float(self.altitude)
        formation["layer_height"] = float(self.altitude_shift)
        formation["final_altitude"] = float(self.enhanced_final_altitude)
        formation["descent_speed"] = float(self.enhanced_descent_speed)
        formation["preferred_acceleration"] = acceleration
        formation["descent_ramp_time"] = _ENHANCED_DESCENT_RAMP_SECONDS
        highest_final_z = max(float(point[2]) for point in target) - float(
            self.altitude) + float(self.enhanced_final_altitude)
        landing_seconds = self._estimate_rtl_landing_seconds(highest_final_z)
        formation["rtl_landing_seconds"] = landing_seconds
        formation["rtl_landing_delay_frames"] = int(ceil(landing_seconds*fps))
        formation["rtl_highest_final_altitude"] = highest_final_z
        markers = get_markers_from_formation(formation)
        if len(markers) != len(drones):
            raise AlgorithmNotReconstructed(_tr("Return marker count does not match drone count."))

        total = len(drones)
        progress_chunk_size = min(_ENHANCED_PROGRESS_CHUNK_SIZE, total)
        descent_keyframes = self._get_sparse_descent_keyframes(
            descent_start_index, descent_index
        )
        for done, (drone, marker) in enumerate(zip(drones, markers), start=1):
            ensure_animation_data_exists_for_object(marker, clean=True)
            track = tracks[drone.name]
            curves = [
                ensure_f_curve_exists_for_data_path_and_index(
                    marker, data_path="location", index=axis
                )
                for axis in range(3)
            ]
            for axis, curve in enumerate(curves):
                points = curve.keyframe_points
                # Preserve the solver's per-frame path and hover, then use only
                # ten control points for the obstacle-free vertical descent.
                selected_keyframes = [
                    (index, index, "LINEAR")
                    for index in range(min(descent_start_index + 1, len(track)))
                ]
                selected_keyframes.extend(descent_keyframes)
                selected_keyframes.sort(key=lambda item: item[0])
                points.add(len(selected_keyframes))
                coordinates = [
                    value
                    for index, track_index, _ in selected_keyframes
                    for value in (
                        int(self.start_frame) + index,
                        float(track[track_index][axis]),
                    )
                ]
                points.foreach_set("co", coordinates)
                for key, (_, _, interpolation) in zip(points, selected_keyframes):
                    key.interpolation = interpolation
                curve.update()

            if report_progress and (
                done % progress_chunk_size == 0 or done == total
            ):
                yield "keyframes", done, total

        context.scene.frame_set(entry.frame_end)
        self.report(
            {"INFO"},
            _tr("Created enhanced return for %d drones in the storyboard: frames %d–%d.")
            % (len(drones), entry.frame_start, entry.frame_end),
        )
        return True

    def modal(self, context, event):
        job = getattr(self, "_enhanced_job", None)
        if job is None:
            return {"CANCELLED"}

        if event.type == "ESC" and job["stage"] == "simulation":
            self._finish_enhanced_job()
            self.report({"INFO"}, _tr("Direct return calculation cancelled."))
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"RUNNING_MODAL"} if event.type == "ESC" else {"PASS_THROUGH"}

        deadline = perf_counter() + 0.025
        try:
            while perf_counter() < deadline:
                if job["stage"] == "simulation":
                    try:
                        job["latest_progress"] = next(job["iterator"])
                    except StopIteration as result:
                        job["stage"] = "descent"
                        job["iterator"] = self._write_enhanced_return(
                            job["storyboard"], result.value, job["source"],
                            job["target"], job["drones"], job["limits"], job["fps"],
                            job["acceleration"], context,
                        )
                        job["latest_progress"] = (0, 0, len(job["drones"]))
                else:
                    try:
                        stage, done, total = next(job["iterator"])
                        job["stage"] = stage
                        job["latest_progress"] = (0, done, total)
                    except StopIteration as result:
                        self._finish_enhanced_job()
                        success = self._postprocess_run(
                            result.value, job["storyboard"], job["drones"], context
                        )
                        return {"FINISHED"} if success else {"CANCELLED"}

            self._update_enhanced_progress(context)
        except AlgorithmNotReconstructed as ex:
            self._finish_enhanced_job()
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        except Exception as ex:
            self._finish_enhanced_job()
            self.report({"ERROR"}, _tr("Direct return failed: %s") % str(ex))
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def _update_enhanced_progress(self, context, *, force=False):
        job = getattr(self, "_enhanced_job", None)
        if job is None:
            return
        now = monotonic()
        frame, done, total = job["latest_progress"]
        raw_pct = int(100 * done / total) if total else 100
        pct = min(
            100,
            (raw_pct // _ENHANCED_PROGRESS_PERCENT_STEP)
            * _ENHANCED_PROGRESS_PERCENT_STEP,
        )
        stage_changed = job.get("displayed_stage") != job["stage"]
        progress_changed = job.get("displayed_pct") != pct
        heartbeat_due = (
            now - job["last_header_update"] >= _ENHANCED_PROGRESS_HEARTBEAT_SECONDS
        )
        if not force and not stage_changed and not progress_changed and not heartbeat_due:
            return
        job["last_header_update"] = now
        job["displayed_stage"] = job["stage"]
        job["displayed_pct"] = pct
        if job["stage"] == "simulation":
            message = _tr("Returning to aerial grid: %d/%d drones arrived (%d%%), frame %d") % (
                done, total, pct, frame,
            )
        elif job["stage"] == "descent":
            message = _tr("Preparing return paths: %d/%d drones (%d%%)") % (
                done, total, pct,
            )
        else:
            message = _tr("Writing return animation: %d/%d drones (%d%%)") % (
                done, total, pct,
            )
        area = job["area"]
        if area is not None:
            area.header_text_set(message)
            area.tag_redraw()
        job["window_manager"].progress_update(pct)

    def _finish_enhanced_job(self):
        job = getattr(self, "_enhanced_job", None)
        if job is None:
            return
        window_manager = job["window_manager"]
        try:
            window_manager.event_timer_remove(job["timer"])
        except (ReferenceError, RuntimeError):
            pass
        try:
            window_manager.progress_end()
        except (ReferenceError, RuntimeError):
            pass
        area = job["area"]
        if area is not None:
            try:
                area.header_text_set(None)
                area.tag_redraw()
            except (ReferenceError, RuntimeError):
                pass
        self._enhanced_job = None

    @staticmethod
    def _get_sparse_descent_keyframes(start_index, end_index):
        """Return ten descent controls: hold, ease-in, cruise, ease-out, hold."""
        descent_steps = end_index - start_index
        if descent_steps <= 0:
            return [(start_index + 1, start_index + 1, "LINEAR")]

        # Two stationary points, two easing-in points, two cruise points,
        # two easing-out points, and two end-hold points.
        offsets = [
            0,
            1,
            max(2, round(descent_steps * 0.05)),
            round(descent_steps * 0.25),
            round(descent_steps * 0.40),
            round(descent_steps * 0.60),
            round(descent_steps * 0.75),
            round(descent_steps * 0.95),
            descent_steps,
            descent_steps + 1,
        ]
        offsets = sorted({max(0, min(offset, descent_steps + 1)) for offset in offsets})
        interpolation_by_offset = {
            0: "LINEAR",
            1: "BEZIER",
            max(2, round(descent_steps * 0.05)): "BEZIER",
            round(descent_steps * 0.25): "LINEAR",
            round(descent_steps * 0.40): "LINEAR",
            round(descent_steps * 0.60): "LINEAR",
            round(descent_steps * 0.75): "BEZIER",
            round(descent_steps * 0.95): "BEZIER",
            descent_steps: "LINEAR",
            descent_steps + 1: "LINEAR",
        }
        return [
            (start_index + offset, start_index + 1 + ordinal,
             interpolation_by_offset.get(offset, "LINEAR"))
            for ordinal, offset in enumerate(offset for offset in offsets if offset > 0)
        ]

    def _append_grid_descent(self, tracks, drones, targets, limits, *, report_progress=True):
        """Wait for every track, settle exactly, then translate the whole grid."""
        fps = limits.fps
        count = max(map(len, tracks.values()))
        endpoints = [Vector(tracks[d.name][-1]) for d in drones]
        targets = [Vector(t) for t in targets]
        # Smooth correction of the solver's <=10 cm endpoint tolerance.
        settle_seconds = 0.25
        for origin, target in zip(endpoints, targets):
            delta = target-origin
            settle_seconds = max(settle_seconds,
                1.5*delta.length / max(limits.max_velocity*fps, 1e-6))
            for component, velocity, accel in zip(delta,
                (limits.max_horizontal_velocity*fps, limits.max_horizontal_velocity*fps,
                 min(limits.max_vertical_up_velocity, limits.max_vertical_down_velocity)*fps),
                (limits.max_acceleration_x*fps*fps, limits.max_acceleration_y*fps*fps,
                 limits.max_acceleration_z*fps*fps)):
                settle_seconds = max(settle_seconds, 1.5*abs(component)/max(velocity,1e-6),
                                     sqrt(6*abs(component)/max(accel,1e-6)))
        settle_steps = max(1, ceil(settle_seconds*fps))
        hover_steps = int(ceil(2.0*fps))
        drop = float(self.altitude-self.enhanced_final_altitude)
        speed = float(self.enhanced_descent_speed)
        acceleration = min(
            max(limits.max_acceleration_z*fps*fps, 1e-6),
            speed / _ENHANCED_DESCENT_RAMP_SECONDS,
        )
        ramp = min(speed/acceleration, sqrt(drop/acceleration)) if drop > 0 else 0.0
        peak = acceleration*ramp
        cruise = max(0.0, (drop-acceleration*ramp*ramp)/peak) if peak > 0 else 0.0
        seconds = 2*ramp+cruise
        descent_steps = max(1, ceil(seconds*fps)) if drop > 0 else 0
        def descent_distance(step):
            if descent_steps <= 0:
                return drop
            t = seconds*step/descent_steps
            if t < ramp:
                return 0.5*acceleration*t*t
            elif t < ramp+cruise:
                return 0.5*acceleration*ramp*ramp+peak*(t-ramp)
            return drop-0.5*acceleration*(seconds-t)**2
        control_keyframes = self._get_sparse_descent_keyframes(0, descent_steps)
        control_offsets = [frame for frame, _, _ in control_keyframes]
        total = len(drones)
        progress_chunk_size = min(_ENHANCED_PROGRESS_CHUNK_SIZE, total)
        for done, (drone, origin, target) in enumerate(
            zip(drones, endpoints, targets), start=1
        ):
            track = tracks[drone.name]
            track.extend(Vector(origin) for _ in range(count-len(track)))
            for step in range(1, settle_steps+1):
                u = step/settle_steps
                track.append(Vector(target) if step == settle_steps else
                             origin+(target-origin)*(u*u*(3-2*u)))
            track.extend(Vector(target) for _ in range(hover_steps))
            for offset in control_offsets:
                distance = descent_distance(min(offset, descent_steps))
                track.append(target-Vector((0,0,distance)))
            if report_progress and (
                done % progress_chunk_size == 0 or done == total
            ):
                yield "descent", done, total
        arrival_index = count-1+settle_steps
        descent_start_index = arrival_index+hover_steps
        return tracks, arrival_index, descent_start_index, descent_start_index+descent_steps

    @staticmethod
    def _estimate_rtl_landing_seconds(height):
        """Timing only: 3 s RTL hover, 1.3 m/s above 1 m, 0.4 m/s below."""
        height = max(float(height), 0.0)
        return 3.0 + max(height-1.0, 0.0)/1.3 + min(height, 1.0)/0.4

    def _apply_drone_size_keyframes(
        self, drones, start_frame: int, end_frame: int, *, start_small=False, end_only=False
    ):

        if end_only:
            bpy.context.scene.frame_set(start_frame)
        for drone in drones:
            current_scale = drone.scale.x
            current_radius = max(drone.dimensions) / 2

            if current_scale > 1e-6 and current_radius > 1e-6:

                base_radius = current_radius / current_scale
                large_scale = 0.5 / base_radius
                small_scale = 0.15 / base_radius
            else:
                large_scale = small_scale = current_scale


            first_scale = small_scale if start_small else large_scale
            if not end_only:
                drone.scale = (first_scale, first_scale, first_scale)
            drone.keyframe_insert(data_path="scale", frame=start_frame)
            if end_only:
                drone.keyframe_insert(data_path="scale", frame=end_frame-1)


            drone.scale = (small_scale, small_scale, small_scale)
            drone.keyframe_insert(data_path="scale", frame=end_frame)


            if drone.animation_data:
                for fcurve in iter_all_f_curves(drone.animation_data):
                    if fcurve.data_path == "scale":
                        for kp in fcurve.keyframe_points:
                            if not end_only or kp.co.x >= start_frame:
                                kp.interpolation = "CONSTANT"
        if end_only:
            bpy.context.scene.frame_set(end_frame)

    def _run_base_rth(
        self,
        storyboard: Storyboard,
        *,
        source: Sequence[Coordinate3D],
        target: Sequence[Coordinate3D],
        context: Context,
    ) -> bool:
        fps = context.scene.render.fps
        diffs = [
            sqrt((s[0] - t[0]) ** 2 + (s[1] - t[1]) ** 2 + (s[2] - t[2]) ** 2)
            for s, t in zip(source, target)
        ]



        max_distance = max(diffs)
        rth_duration = int(ceil((max_distance / self.velocity) * fps))



        last_entry = storyboard.last_entry
        if last_entry is not None:
            last_entry.extend_until(self.start_frame)


        end_of_rth = self.start_frame + rth_duration


        storyboard.add_new_entry(
            formation=create_formation("Return to home", target),
            frame_start=end_of_rth,
            duration=0,
            select=True,
            purpose=StoryboardEntryPurpose.LANDING,
            context=context,
        )

        return True

    def _run_smart_rth(
        self,
        storyboard: Storyboard,
        *,
        source: Sequence[Coordinate3D],
        target: Sequence[Coordinate3D],
        context: Context,
    ) -> bool:
        fps = context.scene.render.fps



        settings = getattr(context.scene.skybrush, "settings", None)
        max_acceleration = settings.max_acceleration if settings else 4
        to_aerial_grid = self._should_return_to_aerial_grid()
        land_speed = min(self.velocity_z, 0.5)
        land_duration = 0 if to_aerial_grid else self.altitude / land_speed


        eps = 2e-3
        with call_api_from_blender_operator(self) as api:
            plan = api.plan_smart_rth(
                source,
                target,
                max_velocity_xy=self.velocity - eps,
                max_velocity_z=self.velocity_z - eps,
                max_acceleration=max_acceleration,
                min_distance=self.spacing,
                rth_model="straight_line_with_neck_to_layers"
                if to_aerial_grid
                else "straight_line_with_neck",
            )
        if not plan.start_times or not plan.durations:
            return False




        entry = storyboard.add_new_entry(
            formation=create_formation("Smart return to home", source),
            frame_start=self.start_frame,
            duration=int(ceil((plan.duration + land_duration) * fps)),
            select=True,
            purpose=StoryboardEntryPurpose.LANDING,
            context=context,
        )
        assert entry is not None
        markers = get_markers_from_formation(entry.formation)


        for marker in markers:
            assert isinstance(marker, Object)
            ensure_animation_data_exists_for_object(marker, clean=True)


        for start_time, duration, inner_points, p, q, marker in zip(
            plan.start_times,
            plan.durations,
            plan.inner_points,
            source,
            target,
            markers,
            strict=True,
        ):
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
            if start_time > 0:
                path_points.append((0, *p))
            path_points.append((start_time, *p))
            path_points.extend(tuple(inner_points))
            path_points.append((start_time + duration, *q))
            if not to_aerial_grid:
                path_points.append(
                    (
                        start_time + duration + land_duration,
                        q[0],
                        q[1],
                        0,
                    )
                )
            for point in path_points:
                frame = round(self.start_frame + point[0] * fps)
                keyframes = (
                    insert[0](frame, point[1]),
                    insert[1](frame, point[2]),
                    insert[2](frame, point[3]),
                )
                for keyframe in keyframes:
                    keyframe.interpolation = "LINEAR"

            for f_curve in f_curves:
                f_curve.update()

        return True

    def _run_smart_rth_for_group(
        self,
        storyboard: Storyboard,
        *,
        source: Sequence[Coordinate3D],
        target: Sequence[Coordinate3D],
        context: Context,
        group: str,
    ) -> bool:

        from sbstudio.plugin.utils.drone_groups import get_drone_group

        drones = list(Collections.find_drones().objects)
        group_idx = [i for i, d in enumerate(drones) if get_drone_group(d) == group]

        if not group_idx:
            self.report(
                {"WARNING"},
                f"No drones tagged as {group}. Falling back to standard smart RTH.",
            )
            return self._run_smart_rth(
                storyboard, source=source, target=target, context=context
            )



        group_source = [source[i] for i in group_idx]
        group_target = [target[i] for i in group_idx]
        name = f"Smart RTH ({group.title()})"

        return self._create_smart_rth_entry_for_group(
            storyboard,
            source=group_source,
            target=group_target,
            start_frame=self.start_frame,
            name=name,
            group=group,
            context=context,
        )

    def _create_smart_rth_entry_for_group(
        self,
        storyboard: Storyboard,
        *,
        source: Sequence[Coordinate3D],
        target: Sequence[Coordinate3D],
        start_frame: int,
        name: str,
        group: str,
        context: Context,
        purpose: StoryboardEntryPurpose = StoryboardEntryPurpose.UNSPECIFIED,
    ) -> bool:

        fps = context.scene.render.fps
        settings = getattr(context.scene.skybrush, "settings", None)
        max_acceleration = settings.max_acceleration if settings else 4
        to_aerial_grid = self._should_return_to_aerial_grid()
        land_speed = min(self.velocity_z, 0.5)
        land_duration = 0 if to_aerial_grid else self.altitude / land_speed

        eps = 2e-3
        with call_api_from_blender_operator(self) as api:
            plan = api.plan_smart_rth(
                source,
                target,
                max_velocity_xy=self.velocity - eps,
                max_velocity_z=self.velocity_z - eps,
                max_acceleration=max_acceleration,
                min_distance=self.spacing,
                rth_model="straight_line_with_neck_to_layers"
                if to_aerial_grid
                else "straight_line_with_neck",
            )
        if not plan.start_times or not plan.durations:
            return False

        entry = storyboard.add_new_entry(
            formation=create_formation(name, source),
            frame_start=start_frame,
            duration=int(ceil((plan.duration + land_duration) * fps)),
            select=True,
            purpose=purpose,
            context=context,
        )
        assert entry is not None
        entry.limit_to_group = group

        markers = get_markers_from_formation(entry.formation)
        for marker in markers:
            assert isinstance(marker, Object)
            ensure_animation_data_exists_for_object(marker, clean=True)

        for start_time, duration, inner_points, p, q, marker in zip(
            plan.start_times,
            plan.durations,
            plan.inner_points,
            source,
            target,
            markers,
            strict=True,
        ):
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
            if start_time > 0:
                path_points.append((0, *p))
            path_points.append((start_time, *p))
            path_points.extend(tuple(inner_points))
            path_points.append((start_time + duration, *q))
            if not to_aerial_grid:
                path_points.append(
                    (
                        start_time + duration + land_duration,
                        q[0],
                        q[1],
                        0,
                    )
                )
            for point in path_points:
                frame = round(start_frame + point[0] * fps)
                keyframes = (
                    insert[0](frame, point[1]),
                    insert[1](frame, point[2]),
                    insert[2](frame, point[3]),
                )
                for keyframe in keyframes:
                    keyframe.interpolation = "LINEAR"
            for f_curve in f_curves:
                f_curve.update()

        return True

    def _validate_start_frame(self, context: Context) -> bool:

        storyboard = get_storyboard(context=context)
        last_frame = storyboard.frame_end if storyboard.last_entry is not None else None





        if last_frame is not None and self.start_frame < last_frame:
            self.report(
                {"ERROR"},
                f"Return to home maneuver must not start before the last entry "
                f"of the storyboard (frame {last_frame})",
            )
            return False

        return True
