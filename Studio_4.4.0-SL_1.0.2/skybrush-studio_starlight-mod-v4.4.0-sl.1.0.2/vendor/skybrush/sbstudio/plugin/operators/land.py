from math import ceil

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy.types import Context

from sbstudio.errors import SkybrushStudioError
from sbstudio.math.nearest_neighbors import find_nearest_neighbors
from sbstudio.plugin.api import call_api_from_blender_operator
from sbstudio.plugin.constants import Collections
from sbstudio.plugin.model.formation import create_formation
from sbstudio.plugin.model.safety_check import get_proximity_warning_threshold
from sbstudio.plugin.model.storyboard import (
    Storyboard,
    StoryboardEntryPurpose,
    get_storyboard,
)
from sbstudio.plugin.utils.evaluator import create_position_evaluator
from sbstudio.plugin.utils.transition import find_transition_constraint_between

from .base import StoryboardOperator

__all__ = ("LandOperator",)


def use_custom_spacing_updated(self, context: Context):
    
    if not self.use_custom_spacing:
        self.spacing = get_proximity_warning_threshold(context)


class LandOperator(StoryboardOperator):
    

    bl_idname = "skybrush.land"
    bl_label = "Land Drones"
    bl_description = "Add a landing maneuver to all the drones"
    bl_options = {"REGISTER", "UNDO"}

    only_with_valid_storyboard = True

    start_frame = IntProperty(
        name="at Frame", description="Start frame of the landing maneuver"
    )

    velocity = FloatProperty(
        name="with Velocity",
        description="Average vertical velocity during the landing maneuver",
        default=1,
        min=0.1,
        soft_min=0.1,
        soft_max=10,
        unit="VELOCITY",
    )

    altitude = FloatProperty(
        name="to Altitude",
        description="Altitude to land to",
        default=0,
        soft_min=-50,
        soft_max=50,
        unit="LENGTH",
    )

    use_custom_spacing = BoolProperty(
        name="Use custom spacing",
        default=False,
        description="When checked, a custom spacing can be given instead of the default proximity warning threshold",
        update=use_custom_spacing_updated,
    )

    spacing = FloatProperty(
        name="Spacing",
        description="Minimum distance between drones during landing",
        default=3,
        min=0.1,
        soft_max=50,
        unit="LENGTH",
    )

    spindown_time = FloatProperty(
        name="Motor spindown delay (sec)",
        description=(
            "Time it takes for the motors to spin down after a successful landing"
        ),
        default=5,
        min=0,
        soft_min=0,
        soft_max=10,
        unit="TIME",
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
        row = layout.row(heading="Spacing")
        row.prop(self, "use_custom_spacing", text="")
        row = row.row()
        row.prop(self, "spacing", text="")
        row.enabled = self.use_custom_spacing
        if self.spacing < get_proximity_warning_threshold(context):
            row.alert = True
            row.label(text="", icon="ERROR")
        layout.prop(self, "spindown_time")

    def invoke(self, context: Context, event):
        self.start_frame = max(
            context.scene.frame_current, get_storyboard(context=context).frame_end
        )

        if not self.use_custom_spacing:
            self.spacing = get_proximity_warning_threshold(context)

        return context.window_manager.invoke_props_dialog(self)

    def execute_on_storyboard(self, storyboard, entries, context):
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

        
        
        
        with create_position_evaluator() as get_positions_of:
            source = get_positions_of(drones, frame=self.start_frame)

        
        target = [(x, y, self.altitude) for x, y, _ in source]

        
        diffs = [s[2] - t[2] for s, t in zip(source, target)]
        if min(diffs) < 0:
            dist = abs(min(diffs))
            self.report(
                {"ERROR"},
                f"At least one drone would have to land upwards by {dist}m",
            )
            return False

        
        fps = context.scene.render.fps
        _, _, dist = find_nearest_neighbors(target)
        if dist < self.spacing:
            with call_api_from_blender_operator(self, "landing planner") as api:
                delays, durations = api.plan_landing(
                    source,
                    min_distance=self.spacing,
                    velocity=self.velocity,
                    target_altitude=self.altitude,
                    spindown_time=self.spindown_time,
                )
        else:
            
            delays = [0] * len(source)
            durations = [diff / self.velocity for diff in diffs]

        delays = [int(ceil(delay * fps)) for delay in delays]
        durations = [int(ceil(duration * fps)) for duration in durations]
        max_duration = max(
            delay + duration for delay, duration in zip(delays, durations)
        )
        post_delays = [
            max_duration - delay - duration
            for delay, duration in zip(delays, durations)
        ]

        
        
        if len(storyboard.entries) > 0:
            last_entry = storyboard.entries[-1]
            last_entry.extend_until(self.start_frame)
        else:
            last_entry = None

        formation = last_entry.formation if last_entry is not None else None
        objects_in_last_formation = list(formation.objects) if formation else []

        
        end_of_landing = self.start_frame + max_duration

        
        entry = storyboard.add_new_entry(
            formation=create_formation("Landing", target),
            frame_start=end_of_landing,
            duration=0,
            select=True,
            purpose=StoryboardEntryPurpose.LANDING,
            context=context,
        )
        assert entry is not None
        entry.transition_type = "MANUAL"

        
        
        if len(storyboard.entries) > 1:
            last_entry = storyboard.entries[-2]
        else:
            last_entry = None

        
        if max(delays) > 0 or max(post_delays) > 0:
            entry.schedule_overrides_enabled = True
            for index, (delay, post_delay) in enumerate(zip(delays, post_delays)):
                if delay > 0 or post_delay > 0:
                    
                    
                    
                    constraint = find_transition_constraint_between(
                        drone=drones[index], storyboard_entry=last_entry
                    )
                    if constraint is not None:
                        marker = constraint.target
                        try:
                            override_index = objects_in_last_formation.index(marker)
                        except ValueError:
                            
                            override_index = -1
                    else:
                        
                        
                        
                        
                        
                        override_index = -1

                    if override_index >= 0:
                        override = entry.add_new_schedule_override()
                        override.pre_delay = delay
                        override.post_delay = post_delay
                        override.index = override_index

        
        bpy.ops.skybrush.recalculate_transitions(scope="TO_SELECTED")
        return True

    def _validate_start_frame(self, context: Context) -> bool:
        
        storyboard = get_storyboard(context=context)
        if storyboard.last_entry is not None:
            last_frame = storyboard.frame_end
        else:
            last_frame = None

        
        
        

        if last_frame is not None and self.start_frame < last_frame:
            self.report(
                {"ERROR"},
                (
                    f"Landing maneuver must not start before the last entry of "
                    f"the storyboard (frame {last_frame})"
                ),
            )
            return False

        return True
