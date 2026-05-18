from math import ceil, inf

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import Context

from sbstudio.errors import SkybrushStudioError
from sbstudio.math.nearest_neighbors import find_nearest_neighbors
from sbstudio.plugin.api import call_api_from_blender_operator, get_api
from sbstudio.plugin.constants import Collections, Formations
from sbstudio.plugin.model.formation import (
    create_formation,
    ensure_formation_consists_of_points,
)
from sbstudio.plugin.model.safety_check import get_proximity_warning_threshold
from sbstudio.plugin.model.storyboard import (
    Storyboard,
    StoryboardEntryPurpose,
    get_storyboard,
)
from sbstudio.plugin.operators.recalculate_transitions import (
    RecalculationTask,
    recalculate_transitions,
)
from sbstudio.plugin.utils.evaluator import create_position_evaluator

from .base import StoryboardOperator

__all__ = ("TakeoffOperator",)


# === Starlight Animator Layer Sequences ===
# Optimized interleave sequences for box takeoff (reduces airflow interference)
INTERLEAVE_8 = [7, 5, 1, 3, 6, 8, 4, 2]
INTERLEAVE_12 = [11, 8, 3, 6, 1, 10, 5, 12, 9, 2, 7, 4]
INTERLEAVE_16 = [13, 10, 5, 2, 9, 14, 1, 6, 15, 12, 7, 4, 11, 16, 3, 8]

# Traditional single-drone array interleave sequences
INTERLEAVE_4 = [3, 1, 4, 2]
INTERLEAVE_9 = [7, 3, 9, 1, 5, 8, 2, 6, 4]


def get_layer_sequence(scheme, spacing_x=1.0, is_traditional=False):
    """Return the interleave sequence for the given scheme."""
    if is_traditional:
        # Traditional array schemes
        if scheme == "T4":
            return INTERLEAVE_4
        elif scheme == "T9":
            return INTERLEAVE_9
        else:  # AUTO
            return INTERLEAVE_4
    else:
        # Box array schemes
        if scheme == "L8":
            return INTERLEAVE_8
        elif scheme == "L12":
            return INTERLEAVE_12
        elif scheme == "L16":
            return INTERLEAVE_16
        else:  # AUTO
            if spacing_x >= 1.4:
                return INTERLEAVE_8
            elif spacing_x >= 1.0:
                return INTERLEAVE_12
            else:
                return INTERLEAVE_16


def apply_starlight_layering(source, groups, scheme="AUTO", spacing_x=1.0):
    """
    Apply Starlight Animator's optimized layer sequence to box takeoff groups.
    
    Args:
        source: List of (x, y, z) positions
        groups: List of group indices from decompose_points (will be replaced)
        scheme: Layer scheme ("AUTO", "L8", "L12", "L16")
        spacing_x: Box spacing in X direction (for AUTO mode)
    
    Returns:
        Modified groups list with Starlight layering applied
    """
    if not source or not groups:
        return groups
    
    # Get the interleave sequence
    sequence = get_layer_sequence(scheme, spacing_x, is_traditional=False)
    seq_len = len(sequence)
    
    # Build a mapping: original_group -> new_layer
    # The sequence defines the layer order for positions within each box
    # For box takeoff, we assume drones are organized in boxes of 8
    new_groups = []
    
    for i, (pos, orig_group) in enumerate(zip(source, groups)):
        # Determine position within box (0-7 for 8-drone boxes)
        box_index = i // 8
        pos_in_box = i % 8
        
        # Apply interleave sequence
        if pos_in_box < seq_len:
            # Map position to layer using sequence
            # sequence[pos_in_box] gives the layer number (1-indexed)
            # Convert to 0-indexed group number
            new_layer = sequence[pos_in_box] - 1
        else:
            # Fallback for positions beyond sequence length
            new_layer = pos_in_box
        
        new_groups.append(new_layer)
    
    return new_groups


def apply_traditional_layering(source, groups, scheme="AUTO", rows=8, cols=8):
    """
    Apply Starlight Animator's optimized layer sequence to traditional single-drone array.
    
    Args:
        source: List of (x, y, z) positions
        groups: List of group indices from decompose_points (will be replaced)
        scheme: Layer scheme ("AUTO", "T4", "T9")
        rows: Number of rows in the grid
        cols: Number of columns in the grid
    
    Returns:
        Modified groups list with Starlight layering applied
    """
    if not source or not groups:
        return groups
    
    # Get the interleave sequence
    sequence = get_layer_sequence(scheme, is_traditional=True)
    seq_len = len(sequence)
    
    # For traditional array, apply sequence based on grid position
    # Assume row-major order
    new_groups = []
    
    for i, (pos, orig_group) in enumerate(zip(source, groups)):
        # Calculate grid position
        row = i // cols
        col = i % cols
        
        # Apply interleave based on sequence length
        if seq_len == 4:
            # 4-layer: 2x2 pattern
            pattern_row = row % 2
            pattern_col = col % 2
            pattern_idx = pattern_row * 2 + pattern_col
        elif seq_len == 9:
            # 9-layer: 3x3 pattern
            pattern_row = row % 3
            pattern_col = col % 3
            pattern_idx = pattern_row * 3 + pattern_col
        else:
            pattern_idx = 0
        
        if pattern_idx < seq_len:
            new_layer = sequence[pattern_idx] - 1
        else:
            new_layer = pattern_idx
        
        new_groups.append(new_layer)
    
    return new_groups


def use_custom_spacing_updated(self, context: Context):
    
    if not self.use_custom_spacing:
        self.spacing = get_proximity_warning_threshold(context)


class TakeoffOperator(StoryboardOperator):
    

    bl_idname = "skybrush.takeoff"
    bl_label = "Takeoff"
    bl_description = "Add a takeoff maneuver to all the drones"
    bl_options = {"REGISTER", "UNDO"}

    only_with_valid_storyboard = True

    start_frame = IntProperty(
        name="at Frame", description="Start frame of the takeoff maneuver"
    )

    velocity = FloatProperty(
        name="with Velocity",
        description="Average vertical velocity during the takeoff maneuver",
        default=1.5,
        min=0.1,
        soft_min=0.1,
        soft_max=10,
        unit="VELOCITY",
    )

    altitude = FloatProperty(
        name="to Altitude",
        description=(
            "Altitude to take off to. In case of layered takeoff "
            "the desired takeoff altitude of the lowest layer"
        ),
        default=6,
        soft_min=0,
        soft_max=50,
        unit="LENGTH",
    )

    
    

    altitude_is_relative = BoolProperty(
        name="Relative Altitude",
        description=(
            "Specifies whether the takeoff altitude is relative to the current "
            "altitude of the drone. Deprecated; not used any more."
        ),
        default=False,
        options={"HIDDEN"},
    )

    use_custom_spacing = BoolProperty(
        name="Use custom spacing",
        default=False,
        description=(
            "When checked, a custom spacing can be given instead of "
            "the default proximity warning threshold"
        ),
        update=use_custom_spacing_updated,
    )

    spacing = FloatProperty(
        name="Spacing",
        description="Minimum distance between drones during takeoff",
        default=3,
        min=0.1,
        soft_max=50,
        unit="LENGTH",
    )

    altitude_shift = FloatProperty(
        name="Layer height",
        description=(
            "Specifies the difference between altitudes of takeoff layers "
            "for multi-phase takeoffs when multiple drones occupy the same "
            "takeoff slot within safety distance."
        ),
        default=5,
        soft_min=0,
        soft_max=50,
        unit="LENGTH",
    )

    # === Starlight Box Array Layering ===
    use_box_layering = BoolProperty(
        name="Box Array Layering",
        default=False,
        description="Use Starlight Animator's optimized layer sequence for box takeoff (reduces airflow interference)",
    )

    box_layer_scheme = EnumProperty(
        name="Box Layer Scheme",
        description="Layering scheme for box takeoff sequence",
        items=[
            ("AUTO", "Auto", "Automatically select scheme based on box spacing"),
            ("L8", "8-Layer", "8-layer interleave (for spacing ≥1.4m)"),
            ("L12", "12-Layer", "12-layer interleave (for spacing 1.0-1.4m)"),
            ("L16", "16-Layer", "16-layer interleave (for spacing <1.0m)"),
        ],
        default="AUTO",
    )

    # === Starlight Traditional Array Layering ===
    use_traditional_layering = BoolProperty(
        name="Traditional Array Layering",
        default=False,
        description="Use Starlight Animator's optimized layer sequence for traditional single-drone array takeoff",
    )

    traditional_layer_scheme = EnumProperty(
        name="Traditional Layer Scheme",
        description="Layering scheme for traditional array takeoff sequence",
        items=[
            ("AUTO", "Auto", "Automatically select scheme (4-layer)"),
            ("T4", "4-Layer", "4-layer interleave [3,1,4,2]"),
            ("T9", "9-Layer", "9-layer interleave [7,3,9,1,5,8,2,6,4]"),
        ],
        default="AUTO",
    )

    # === Batch Takeoff for Traditional Array ===
    use_batch_takeoff = BoolProperty(
        name="Batch Takeoff",
        default=False,
        description="Enable separate takeoff parameters for traditional array (creates two storyboard entries)",
    )

    # Batch takeoff parameters (for traditional array)
    batch_start_frame = IntProperty(
        name="Trad Start Frame",
        description=(
            "Start frame for traditional array takeoff. Can be set INDEPENDENTLY "
            "from the main start frame - the traditional group can take off earlier, "
            "later, or simultaneously with the box group."
        ),
        default=1,
    )

    batch_velocity = FloatProperty(
        name="with Velocity",
        description="Average vertical velocity for traditional array batch takeoff",
        default=1.5,
        min=0.1,
        soft_min=0.1,
        soft_max=10,
        unit="VELOCITY",
    )

    batch_altitude = FloatProperty(
        name="to Altitude",
        description="Altitude for traditional array batch takeoff",
        default=6,
        soft_min=0,
        soft_max=50,
        unit="LENGTH",
    )

    batch_altitude_shift = FloatProperty(
        name="Layer height",
        description="Layer height for traditional array batch takeoff",
        default=5,
        soft_min=0,
        soft_max=50,
        unit="LENGTH",
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
        row = layout.row()
        row.prop(self, "altitude_shift")
        if self.altitude_shift < self.spacing:
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
        
        # Box array layering section
        layout.separator()
        layout.prop(self, "use_box_layering")
        if self.use_box_layering:
            box = layout.box()
            box.prop(self, "box_layer_scheme")
        
        # Traditional array layering section
        layout.separator()
        layout.prop(self, "use_traditional_layering")
        if self.use_traditional_layering:
            box = layout.box()
            box.prop(self, "traditional_layer_scheme")
            
            # Batch takeoff option
            box.separator()
            box.prop(self, "use_batch_takeoff")
            if self.use_batch_takeoff:
                batch_box = box.box()
                batch_box.label(text="Traditional Array Batch Takeoff")
                batch_box.prop(self, "batch_start_frame")
                batch_box.prop(self, "batch_velocity")
                batch_box.prop(self, "batch_altitude")
                batch_box.prop(self, "batch_altitude_shift")

    def invoke(self, context: Context, event):
        
        
        
        start, end = self._get_valid_range_for_start_frame(context)
        self.start_frame = int(max(min(context.scene.frame_current, end), start))

        if not self.use_custom_spacing:
            self.spacing = get_proximity_warning_threshold(context)

        return context.window_manager.invoke_props_dialog(self)

    def execute_on_storyboard(self, storyboard: Storyboard, entries, context: Context):
        try:
            success = self._run(storyboard, context=context)
        except SkybrushStudioError:
            
            success = False
        return {"FINISHED"} if success else {"CANCELLED"}

    def _run(self, storyboard: Storyboard, *, context: Context) -> bool:
        bpy.ops.skybrush.prepare()

        if not self._validate_start_frame(context):
            return False

        drones = Collections.find_drones().objects
        if not drones:
            return False

        # Auto-migration: if no drone has sb_group tag but sb_mixed_box_count is set,
        # tag drones automatically (legacy project compatibility)
        try:
            from sbstudio.plugin.utils.drone_groups import (
                auto_tag_drones_by_count, get_drone_group,
            )
            has_any_tag = any(get_drone_group(d) for d in drones)
            if not has_any_tag:
                scene = context.scene
                box_n = int(scene.get("sb_mixed_box_count", 0))
                trad_n = int(scene.get("sb_mixed_trad_count", 0))
                if box_n > 0 or trad_n > 0:
                    auto_tag_drones_by_count(list(drones), box_n, trad_n)
                    self.report({"INFO"}, f"Auto-tagged drones: {box_n} BOX, {trad_n} TRAD")
        except Exception as e:
            pass  # Migration is best-effort; don't break takeoff
        
        # Check if batch takeoff is enabled (for mixed mode)
        if self.use_batch_takeoff and self.use_traditional_layering:
            return self._run_batch_takeoff(storyboard, drones, context)
        else:
            return self._run_single_takeoff(storyboard, drones, context)

    def _run_single_takeoff(self, storyboard: Storyboard, drones, context: Context) -> bool:
        """Standard single takeoff (original logic)"""
        source, target, _ = create_helper_formation_for_takeoff_and_landing(
            drones,
            frame=self.start_frame,
            base_altitude=self.altitude,
            layer_height=self.altitude_shift,
            min_distance=self.spacing,
            operator=self,
        )

        
        diffs = [t[2] - s[2] for s, t in zip(source, target)]
        if min(diffs) < 0:
            dist = abs(min(diffs))
            self.report(
                {"ERROR"},
                f"At least one drone would have to take off downwards by {dist}m",
            )
            return False

        
        
        fps = context.scene.render.fps
        takeoff_durations = [int(ceil((diff / self.velocity) * fps)) for diff in diffs]

        
        
        takeoff_duration = max(takeoff_durations)
        delays = [takeoff_duration - d for d in takeoff_durations]

        
        end_of_takeoff = self.start_frame + takeoff_duration
        if len(storyboard.entries) > 1:
            assert storyboard.second_entry is not None
            first_frame = storyboard.second_entry.frame_start
            if first_frame < end_of_takeoff:
                self.report(
                    {"ERROR"},
                    f"Takeoff maneuver needs at least {takeoff_duration} frames; "
                    f"there is not enough time after the first entry of the "
                    f"storyboard (frame {first_frame})",
                )
                return False

        
        
        
        
        
        
        entry = storyboard.first_entry
        if entry is None:
            entry = storyboard.add_new_entry(
                formation=create_formation(Formations.TAKEOFF_GRID, source),
                frame_start=self.start_frame,
                duration=0,
                purpose=StoryboardEntryPurpose.TAKEOFF,
                select=False,
                context=context,
            )
        else:
            formation = entry.formation
            if formation is None:
                self.report(
                    {"ERROR"},
                    "First storyboard entry must have an associated formation",
                )
            ensure_formation_consists_of_points(formation, source)

        
        entry = storyboard.add_new_entry(
            formation=create_formation(Formations.TAKEOFF, target),
            frame_start=end_of_takeoff,
            duration=0,
            purpose=StoryboardEntryPurpose.TAKEOFF,
            select=True,
            context=context,
        )
        assert entry is not None
        entry.transition_type = "MANUAL"

        
        if delays and max(delays) > 0:
            entry.schedule_overrides_enabled = True
            for index, delay in enumerate(delays):
                if delay > 0:
                    override = entry.add_new_schedule_override()
                    override.index = index
                    override.pre_delay = delay

        
        
        tasks = [
            RecalculationTask.for_entry_by_index(storyboard.entries, 0),
            RecalculationTask.for_entry_by_index(storyboard.entries, 1),
        ]
        if len(storyboard.entries) > 2:
            tasks.append(RecalculationTask.for_entry_by_index(storyboard.entries, 2))

        start_of_scene = min(context.scene.frame_start, storyboard.frame_start)
        try:
            with call_api_from_blender_operator(self, "transition planner"):
                recalculate_transitions(tasks, start_of_scene=start_of_scene)
        except Exception:
            return False

        return True

    def _run_batch_takeoff(self, storyboard: Storyboard, drones, context: Context) -> bool:
        """Batch takeoff for mixed mode: two INDEPENDENT storyboard entries.
        
        Each entry has limit_to_group set, so only its group of drones participates.
        The two entries can be at ANY frame_start (user controls order). Non-participating
        drones simply keep their position (the transition planner skips them).
        
        Strategy:
        - Compute box_target (with box layering) and trad_target (with trad layering)
        - Create "Takeoff (Box)" entry with ONLY box_target as formation, limit=BOX
        - Create "Takeoff (Trad)" entry with ONLY trad_target as formation, limit=TRAD
        - Each entry has its own schedule_overrides keyed by GLOBAL drone index
        - Storyboard entries are sorted by frame_start automatically
        """
        scene = context.scene
        box_count = int(scene.get("sb_mixed_box_count", 0))
        trad_count = int(scene.get("sb_mixed_trad_count", 0))
        n = len(drones)
        
        # Validate mixed mode: must have both groups
        if box_count <= 0 or trad_count <= 0 or (box_count + trad_count) != n:
            self.report(
                {"WARNING"},
                f"Batch takeoff requires mixed mode takeoff grid (box={box_count}, trad={trad_count}, total={n}). Falling back to single takeoff.",
            )
            return self._run_single_takeoff(storyboard, drones, context)
        
        # Get current source positions of all drones
        with create_position_evaluator() as get_positions_of:
            source = list(get_positions_of(drones, frame=self.start_frame))
        
        box_source = source[:box_count]
        trad_source = source[box_count:]
        
        # === Compute targets for each group, independently ===
        box_target = self._compute_targets(
            box_source,
            base_altitude=self.altitude,
            layer_height=self.altitude_shift,
            use_layering=self.use_box_layering,
            scheme=self.box_layer_scheme,
            spacing_x=self.spacing,
            is_traditional=False,
        )
        trad_target = self._compute_targets(
            trad_source,
            base_altitude=self.batch_altitude,
            layer_height=self.batch_altitude_shift,
            use_layering=self.use_traditional_layering,
            scheme=self.traditional_layer_scheme,
            spacing_x=1.0,
            is_traditional=True,
        )
        
        fps = context.scene.render.fps
        
        # === Compute Box takeoff timing ===
        box_diffs = [t[2] - s[2] for s, t in zip(box_source, box_target)]
        if box_diffs and min(box_diffs) < 0:
            self.report({"ERROR"}, f"Box: drone would take off downwards by {abs(min(box_diffs))}m")
            return False
        box_durations = [int(ceil((d / self.velocity) * fps)) if d > 0 else 0 for d in box_diffs]
        box_takeoff_dur = (max(box_durations) if box_durations else 1) + 1  # +1 safety buffer
        end_of_box_takeoff = self.start_frame + box_takeoff_dur
        # Per-drone delays: keyed by GLOBAL drone index (box drones are 0..box_count-1)
        box_delays = [max(0, box_takeoff_dur - d - 1) for d in box_durations]
        
        # === Compute Trad takeoff timing ===
        trad_diffs = [t[2] - s[2] for s, t in zip(trad_source, trad_target)]
        if trad_diffs and min(trad_diffs) < 0:
            self.report({"ERROR"}, f"Trad: drone would take off downwards by {abs(min(trad_diffs))}m")
            return False
        trad_durations = [int(ceil((d / self.batch_velocity) * fps)) if d > 0 else 0 for d in trad_diffs]
        trad_takeoff_dur = (max(trad_durations) if trad_durations else 1) + 1
        end_of_trad_takeoff = self.batch_start_frame + trad_takeoff_dur
        trad_delays = [max(0, trad_takeoff_dur - d - 1) for d in trad_durations]
        
        # === Ensure takeoff grid entry exists ===
        entry = storyboard.first_entry
        if entry is None:
            entry = storyboard.add_new_entry(
                formation=create_formation(Formations.TAKEOFF_GRID, source),
                frame_start=min(self.start_frame, self.batch_start_frame),
                duration=0,
                purpose=StoryboardEntryPurpose.TAKEOFF,
                select=False,
                context=context,
            )
        else:
            formation = entry.formation
            if formation is None:
                self.report({"ERROR"}, "First storyboard entry must have an associated formation")
                return False
            ensure_formation_consists_of_points(formation, source)
        
        # === Create Box and Trad takeoff entries ===
        # CRITICAL BUG FIX: storyboard.add_new_entry calls _sort_entries() which
        # reorders elements in CollectionProperty. The PropertyGroup wrapper
        # returned by add_new_entry becomes STALE after a subsequent sort (it
        # may now point to a different slot in memory). So we keep formation
        # OBJECT references (which are stable) and re-fetch entries by formation
        # AFTER all adds are complete.
        box_formation = create_formation("Takeoff (Box)", box_target)
        storyboard.add_new_entry(
            formation=box_formation,
            frame_start=end_of_box_takeoff,
            duration=0,
            purpose=StoryboardEntryPurpose.TAKEOFF,
            select=False,
            context=context,
        )
        
        trad_formation = create_formation("Takeoff (Trad)", trad_target)
        storyboard.add_new_entry(
            formation=trad_formation,
            frame_start=end_of_trad_takeoff,
            duration=0,
            purpose=StoryboardEntryPurpose.TAKEOFF,
            select=True,
            context=context,
        )
        
        # Re-fetch entries via formation references (stable identity).
        # Track positions in the same iteration to avoid list.index() equality issues.
        entries_list = list(storyboard.entries)
        box_entry = None
        trad_entry = None
        box_pos = -1
        trad_pos = -1
        for i, e in enumerate(entries_list):
            if e.formation == box_formation:
                box_entry = e
                box_pos = i
            elif e.formation == trad_formation:
                trad_entry = e
                trad_pos = i
        assert box_entry is not None and trad_entry is not None
        
        box_entry.transition_type = "AUTO"
        box_entry.limit_to_group = "BOX"
        trad_entry.transition_type = "AUTO"
        trad_entry.limit_to_group = "TRAD"
        
        # === Compute predecessor end-frames (entries_list is already sorted) ===
        box_pred_end = entries_list[box_pos - 1].frame_end if box_pos > 0 else (context.scene.frame_start or 0)
        trad_pred_end = entries_list[trad_pos - 1].frame_end if trad_pos > 0 else (context.scene.frame_start or 0)
        box_gap = max(0, self.start_frame - box_pred_end)
        trad_gap = max(0, self.batch_start_frame - trad_pred_end)
        
        # === Whichever group takes off LATER must have purpose=UNSPECIFIED ===
        # Reason: Skybrush validates that TAKEOFF entries must precede SHOW entries.
        # If both BOX and TRAD entries are marked TAKEOFF but the user inserts a
        # SHOW pattern between them, validation fails because the later TAKEOFF
        # entry appears AFTER a SHOW entry. So we mark only the EARLIER one as
        # TAKEOFF; the later one is UNSPECIFIED (it's logically a transition,
        # not a takeoff in the show structure sense).
        if box_entry.frame_start <= trad_entry.frame_start:
            # BOX takes off first → BOX is the canonical TAKEOFF; TRAD is later
            trad_entry.purpose = StoryboardEntryPurpose.UNSPECIFIED.name
        else:
            # TRAD takes off first → TRAD is the canonical TAKEOFF; BOX is later
            box_entry.purpose = StoryboardEntryPurpose.UNSPECIFIED.name
        
        # === Apply schedule overrides (with gap added) ===
        # Each drone's total pre_delay = gap_to_takeoff_start + layer_delay
        box_total_delays = [box_gap + d for d in box_delays]
        if box_total_delays and max(box_total_delays) > 0:
            box_entry.schedule_overrides_enabled = True
            for global_idx, total in enumerate(box_total_delays):
                if total > 0:
                    override = box_entry.add_new_schedule_override()
                    override.index = global_idx  # GLOBAL drone index (0..box_count-1)
                    override.pre_delay = total
        
        trad_total_delays = [trad_gap + d for d in trad_delays]
        if trad_total_delays and max(trad_total_delays) > 0:
            trad_entry.schedule_overrides_enabled = True
            for local_idx, total in enumerate(trad_total_delays):
                if total > 0:
                    override = trad_entry.add_new_schedule_override()
                    # Trad drones are box_count..(box_count+trad_count-1) in global indexing
                    override.index = box_count + local_idx
                    override.pre_delay = total
        
        # === Recalculate transitions for all entries ===
        tasks = [
            RecalculationTask.for_entry_by_index(storyboard.entries, i)
            for i in range(len(storyboard.entries))
        ]
        
        start_of_scene = min(context.scene.frame_start, storyboard.frame_start)
        try:
            with call_api_from_blender_operator(self, "transition planner"):
                recalculate_transitions(tasks, start_of_scene=start_of_scene)
        except Exception:
            return False
        
        self.report(
            {"INFO"},
            f"Box: {self.start_frame}->{end_of_box_takeoff} ({box_count} drones); "
            f"Trad: {self.batch_start_frame}->{end_of_trad_takeoff} ({trad_count} drones)",
        )
        return True
    
    def _compute_targets(self, source, *, base_altitude, layer_height,
                          use_layering, scheme, spacing_x, is_traditional):
        """Compute target positions for a group of drones, applying layering if enabled."""
        n = len(source)
        if n == 0:
            return []
        
        if use_layering:
            # Apply Starlight Animator's layering
            groups = [0] * n
            if is_traditional:
                cols = max(1, int(n ** 0.5))
                rows = (n + cols - 1) // cols
                groups = apply_traditional_layering(source, groups, scheme=scheme, rows=rows, cols=cols)
            else:
                groups = apply_starlight_layering(source, groups, scheme=scheme, spacing_x=spacing_x)
        else:
            # Use Studio's decompose_points
            min_distance = self.spacing
            if n >= 2:
                _, _, dist = find_nearest_neighbors(source)
            else:
                dist = float('inf')
            if dist < min_distance and n >= 2:
                with call_api_from_blender_operator(self, "point decomposition") as api:
                    groups = api.decompose_points(source, min_distance=min_distance, method="greedy")
            else:
                groups = [0] * n
        
        num_groups = max(groups) + 1 if groups else 0
        target = [
            (x, y, base_altitude + (num_groups - g - 1) * layer_height)
            for (x, y, _), g in zip(source, groups)
        ]
        return target

    def _get_valid_range_for_start_frame(self, context: Context) -> tuple[float, float]:
        
        
        storyboard = get_storyboard(context=context)
        if len(storyboard.entries) <= 0:
            
            return -inf, inf
        elif len(storyboard.entries) == 1:
            
            assert storyboard.first_entry is not None
            return storyboard.first_entry.frame_end, inf
        else:
            
            
            assert storyboard.first_entry is not None
            assert storyboard.second_entry is not None
            return storyboard.first_entry.frame_end, storyboard.second_entry.frame_start

    def _validate_start_frame(self, context: Context) -> bool:
        
        start, end = self._get_valid_range_for_start_frame(context)
        if self.start_frame < start:
            self.report(
                {"ERROR"},
                (
                    f"Takeoff maneuver must start after the first (takeoff "
                    f"grid) entry of the storyboard (frame {start})"
                ),
            )
            return False

        if self.start_frame >= end:
            self.report(
                {"ERROR"},
                (
                    f"Takeoff maneuver must start before the second "
                    f"entry of the storyboard (frame {end})"
                ),
            )
            return False

        return True


def create_helper_formation_for_takeoff_and_landing(
    drones,
    *,
    frame: int,
    base_altitude: float,
    layer_height: float,
    min_distance: float,
    flatten_source: bool = False,
    operator=None,
):
    
    
    with create_position_evaluator() as get_positions_of:
        source = get_positions_of(drones, frame=frame)
    
    
    if flatten_source:
        min_alt = min(p[2] for p in source)
        source = [(p[0], p[1], min_alt) for p in source]

    
    
    # Check if we should use Starlight layering
    use_box_layering = getattr(operator, "use_box_layering", False) if operator else False
    use_trad_layering = getattr(operator, "use_traditional_layering", False) if operator else False
    
    if use_box_layering or use_trad_layering:
        # Use Starlight Animator's optimized layer sequence
        # In advanced mode, spacing parameter is ignored (as per user requirement)
        box_scheme = getattr(operator, "box_layer_scheme", "AUTO") if operator else "AUTO"
        trad_scheme = getattr(operator, "traditional_layer_scheme", "AUTO") if operator else "AUTO"
        spacing_x = getattr(operator, "spacing", 1.0) if operator else 1.0
        
        # Detect mixed mode from scene metadata
        try:
            scene = bpy.context.scene
            box_count = int(scene.get("sb_mixed_box_count", 0))
            trad_count = int(scene.get("sb_mixed_trad_count", 0))
        except Exception:
            box_count = trad_count = 0
        
        n = len(source)
        is_mixed = box_count > 0 and trad_count > 0 and (box_count + trad_count) == n
        
        groups = [0] * n
        
        if is_mixed:
            # Mixed mode: apply different layering to each group, compute target
            # heights INDEPENDENTLY for each group (both start from base_altitude).
            # Returns target directly to avoid combining num_groups across groups.
            box_src = source[:box_count]
            trad_src = source[box_count:]
            box_groups = [0] * box_count
            trad_groups = [0] * trad_count
            
            if use_box_layering:
                box_groups = apply_starlight_layering(box_src, box_groups, scheme=box_scheme, spacing_x=spacing_x)
            if use_trad_layering:
                cols = max(1, int(trad_count ** 0.5))
                rows = (trad_count + cols - 1) // cols
                trad_groups = apply_traditional_layering(trad_src, trad_groups, scheme=trad_scheme, rows=rows, cols=cols)
            
            # Independent altitude computation: each group has its own num_groups
            box_num = (max(box_groups) + 1) if box_groups else 0
            trad_num = (max(trad_groups) + 1) if trad_groups else 0
            
            box_target = [
                (x, y, base_altitude + (box_num - g - 1) * layer_height)
                for (x, y, _), g in zip(box_src, box_groups)
            ]
            trad_target = [
                (x, y, base_altitude + (trad_num - g - 1) * layer_height)
                for (x, y, _), g in zip(trad_src, trad_groups)
            ]
            target = list(box_target) + list(trad_target)
            # Return early to bypass shared num_groups computation below
            return source, target, list(box_groups) + list(trad_groups)
        else:
            # Single-mode: apply ONE scheme to all drones
            if use_box_layering:
                groups = apply_starlight_layering(source, groups, scheme=box_scheme, spacing_x=spacing_x)
            elif use_trad_layering:
                # Estimate grid dimensions (assume square-ish grid)
                cols = max(1, int(n ** 0.5))
                rows = (n + cols - 1) // cols
                groups = apply_traditional_layering(source, groups, scheme=trad_scheme, rows=rows, cols=cols)
    else:
        # Original Studio logic: use decompose_points
        _, _, dist = find_nearest_neighbors(source)
        if dist < min_distance:
            if operator is not None:
                with call_api_from_blender_operator(operator, "point decomposition") as api:
                    groups = api.decompose_points(
                        source, min_distance=min_distance, method="greedy"
                    )
            else:
                groups = get_api().decompose_points(
                    source, min_distance=min_distance, method="greedy"
                )
        else:
            
            groups = [0] * len(source)

    num_groups = max(groups) + 1 if groups else 0

    
    target = [
        (x, y, base_altitude + (num_groups - group - 1) * layer_height)
        for (x, y, _), group in zip(source, groups)
    ]

    return source, target, groups
