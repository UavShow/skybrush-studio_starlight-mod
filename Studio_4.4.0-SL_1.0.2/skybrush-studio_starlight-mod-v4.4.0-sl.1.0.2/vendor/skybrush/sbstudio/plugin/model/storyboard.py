from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from operator import attrgetter
from typing import TYPE_CHECKING
from uuid import uuid4

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from sbstudio.api.types import Mapping
from sbstudio.plugin.constants import (
    DEFAULT_STORYBOARD_ENTRY_DURATION,
    DEFAULT_STORYBOARD_TRANSITION_DURATION,
    Collections,
)
from sbstudio.plugin.errors import StoryboardValidationError
from sbstudio.plugin.props import FormationProperty
from sbstudio.plugin.utils import sort_collection, with_context
from sbstudio.utils import consecutive_pairs

from .formation import count_markers_in_formation
from .mixins import ListMixin

if TYPE_CHECKING:
    from bpy.types import (
        Collection,
        Context,
        bpy_prop_collection,
    )

__all__ = (
    "ScheduleOverride",
    "StoryboardEntry",
    "StoryboardEntryOrTransition",
    "Storyboard",
    "StoryboardEntryPurpose",
)


class ScheduleOverride(PropertyGroup):
    

    enabled = BoolProperty(
        name="Enabled",
        description="Whether this override entry is enabled",
        default=True,
        options=set(),
    )

    index = IntProperty(
        name="Index",
        description=(
            "0-based index of the marker in the source formation that the "
            "override refers to"
        ),
        default=0,
        min=0,
        options=set(),
    )

    pre_delay = IntProperty(
        name="Departure delay",
        description=(
            "Number of frames between the start of the entire transition and "
            "the departure of the drone assigned to this source marker"
        ),
        min=0,
    )

    post_delay = IntProperty(
        name="Arrival delay",
        description=(
            "Number of frames between the end of the entire transition and the "
            "arrival of the drone assigned to this source marker"
        ),
        min=0,
    )

    @property
    def label(self) -> str:
        parts: list[str] = [f"@{self.index}"]
        if self.pre_delay != 0:
            parts.append(f"dep {self.pre_delay}")
        if self.post_delay != 0:
            parts.append(f"arr {self.post_delay}")
        return " | ".join(parts)


def _handle_formation_change(self: StoryboardEntry, context: Context | None = None):
    if not self.is_name_customized:
        self.name = self.formation.name if self.formation else ""


def _handle_mapping_change(self: StoryboardEntry, context: Context | None = None):
    self._invalidate_decoded_mapping()


def _get_frame_end(self: StoryboardEntry) -> int:
    return self.frame_start + self.duration - 1


def _set_frame_end(self: StoryboardEntry, value: int) -> None:
    
    if value <= self.frame_start:
        self.frame_start = value
        self.duration = 1
    else:
        self.duration = value - self.frame_start + 1


@dataclass(frozen=True)
class _StoryboardEntryPurposeMixin:
    ui_name: str
    order: int


class StoryboardEntryPurpose(_StoryboardEntryPurposeMixin, enum.Enum):
    

    UNSPECIFIED = "Unspecified", 0
    TAKEOFF = "Takeoff", 1
    SHOW = "Show", 2
    LANDING = "Landing", 3

    @property
    def bpy_enum_item(self) -> tuple[str, str, str, int]:
        return (self.name, self.ui_name, "", self.order)


class StoryboardEntry(PropertyGroup):
    

    maybe_uuid_do_not_use = StringProperty(
        name="Identifier",
        description=(
            "Unique identifier for this storyboard entry; must not change "
            "throughout the lifetime of the entry."
        ),
        default="",
        options={"HIDDEN"},
    )
    is_name_customized = BoolProperty(
        name="Custom Name",
        description=(
            "Keeps the name of the storyboard entry when the associated "
            "formation changes"
        ),
        default=False,
        options=set(),
    )
    formation = FormationProperty(
        description=(
            "Formation to use in this storyboard entry. Leave empty to mark this "
            "interval in the show as a segment that should not be affected by "
            "formation constraints"
        ),
        update=_handle_formation_change,
        options=set(),
    )
    frame_start = IntProperty(
        name="Start Frame",
        description="Frame when this formation should start in the show",
        default=0,
        options=set(),
    )
    duration = IntProperty(
        name="Duration",
        description="Duration of this formation",
        min=1,
        default=1,
        options=set(),
    )
    frame_end = IntProperty(
        name="End Frame",
        description="Frame when this formation should end in the show",
        get=_get_frame_end,
        set=_set_frame_end,
        options=set(),
    )
    transition_type = EnumProperty(
        items=[
            ("MANUAL", "Manual", "", 1),
            ("AUTO", "Auto", "", 2),
        ],
        name="Type",
        description="Type of transition between the previous formation and this one. "
        "Manual transitions map the nth vertex of the initial formation to the nth "
        "vertex of the target formation; auto-matched transitions find an "
        "optimal mapping between vertices of the initial and the target formation",
        default="AUTO",
        options=set(),
    )
    transition_schedule = EnumProperty(
        items=[
            ("SYNCHRONIZED", "Synchronized", "", 1),
            ("STAGGERED", "Staggered", "", 2),
        ],
        name="Schedule",
        description=(
            "Time schedule of departures and arrivals during the transition between "
            "the previous formation and this one. Note that collision-free "
            "trajectories are guaranteed only for synchronized transitions"
        ),
        default="SYNCHRONIZED",
        options=set(),
    )

    purpose = EnumProperty(
        items=[
            StoryboardEntryPurpose.UNSPECIFIED.bpy_enum_item,
            StoryboardEntryPurpose.TAKEOFF.bpy_enum_item,
            StoryboardEntryPurpose.SHOW.bpy_enum_item,
            StoryboardEntryPurpose.LANDING.bpy_enum_item,
        ],
        name="Purpose",
        description=(
            "The purpose of the entry in the show. A valid show must start with 0 or more "
            "takeoff entries, followed by any number of show entries, and end with 0 or more "
            "landing entries."
        ),
        default=StoryboardEntryPurpose.UNSPECIFIED.name,
    )

    pre_delay_per_drone_in_frames = FloatProperty(
        name="Departure delay",
        description=(
            "Number of frames to wait between the start times of drones "
            "in a staggered transition"
        ),
        min=0,
        unit="TIME",
        step=100,  
    )
    post_delay_per_drone_in_frames = FloatProperty(
        name="Arrival delay",
        description=(
            "Number of frames to wait between the arrival times of drones "
            "in a staggered transition"
        ),
        min=0,
        unit="TIME",
        step=100,  
    )
    schedule_overrides = CollectionProperty(type=ScheduleOverride)
    schedule_overrides_enabled = BoolProperty(
        name="Schedule overrides enabled",
        description=(
            "Whether the schedule overrides associated to the current entry are enabled"
        ),
    )
    active_schedule_override_entry_index = IntProperty(
        name="Selected override entry index",
        description="Index of the schedule override entry currently being edited",
    )
    is_locked = BoolProperty(
        name="Locked",
        description=(
            "Whether the transition is locked. Locked transitions are never "
            "re-calculated"
        ),
    )
    
    # === Starlight Animator: per-entry drone group filter ===
    limit_to_group = EnumProperty(
        items=[
            ("ALL", "All drones", "All drones participate in this transition", 1),
            ("BOX", "Box array only", "Only box-array drones participate (others keep position)", 2),
            ("TRAD", "Traditional array only", "Only traditional single-drone array participates", 3),
        ],
        name="Drone Group",
        description=(
            "Restrict this transition to a specific drone group. Non-participating "
            "drones keep their position from the previous entry. Use this to schedule "
            "asynchronous group performances (e.g. box array shows a pattern while "
            "traditional pyro drones remain grounded). Leave 'All drones' for normal "
            "behavior."
        ),
        default="ALL",
        options=set(),
    )

    
    

    mapping = StringProperty(
        name="Mapping",
        description=(
            "Mapping where the i-th element is the index of the drone that "
            "marker i was matched to in the storyboard entry, or -1 if the "
            "marker is unmatched."
        ),
        default="",
        options={"HIDDEN"},
        update=_handle_mapping_change,
    )

    sort_key = attrgetter("frame_start", "frame_end")
    """Sorting key for storyboard entries."""

    _decoded_mapping: Mapping | None = None
    """Decoded mapping of the storyboard entry."""

    @property
    def active_schedule_override_entry(self) -> ScheduleOverride | None:
        
        index = self.active_schedule_override_entry_index
        if index is not None and index >= 0 and index < len(self.schedule_overrides):
            return self.schedule_overrides[index]
        else:
            return None

    @active_schedule_override_entry.setter
    def active_schedule_override_entry(self, entry: ScheduleOverride | None):
        if entry is None:
            self.active_schedule_override_entry_index = -1
            return

        for i, entry_in_collection in enumerate(self.schedule_overrides):
            if entry_in_collection == entry:
                self.active_schedule_override_entry_index = i
                return
        else:
            self.active_schedule_override_entry_index = -1

    @with_context
    def add_new_schedule_override(
        self,
        *,
        select: bool = False,
        context: Context | None = None,
    ) -> ScheduleOverride:
        
        entry = self.schedule_overrides.add()
        if select:
            self.active_schedule_override_entry = entry
        return entry

    def contains_frame(self, frame: int) -> bool:
        
        return 0 <= (frame - self.frame_start) < self.duration

    def extend_until(self, frame: int) -> None:
        
        diff = int(frame) - self.frame_end
        if diff > 0:
            self.duration += diff

    @property
    def id(self) -> str:
        
        if not self.maybe_uuid_do_not_use:
            
            self.maybe_uuid_do_not_use = uuid4().hex
        return self.maybe_uuid_do_not_use

    @property
    def is_staggered(self) -> bool:
        
        return self.transition_schedule == "STAGGERED"

    def get_enabled_schedule_override_map(self) -> dict[int, ScheduleOverride]:
        
        result: dict[int, ScheduleOverride] = {}

        if self.schedule_overrides_enabled:
            for override in self.schedule_overrides:
                if override.enabled:
                    result[override.index] = override

        return result

    def get_mapping(self) -> Mapping | None:
        
        if self._decoded_mapping is None:
            encoded_mapping = self.mapping.strip()
            if (
                not encoded_mapping
                or len(encoded_mapping) < 2
                or encoded_mapping[0] != "["
                or encoded_mapping[-1] != "]"
            ):
                return None
            else:
                self._decoded_mapping = json.loads(encoded_mapping)

        return self._decoded_mapping

    def remove_active_schedule_override_entry(self) -> None:
        
        entry = self.active_schedule_override_entry
        if not entry:
            return

        index = self.active_schedule_override_entry_index
        self.schedule_overrides.remove(index)
        self.active_schedule_override_entry_index = min(
            max(0, index), len(self.schedule_overrides)
        )

    def update_mapping(self, mapping: Mapping | None) -> None:
        
        if mapping is None:
            self.mapping = ""
        else:
            self.mapping = json.dumps(mapping)
        assert self._decoded_mapping is None

    def _invalidate_decoded_mapping(self) -> None:
        self._decoded_mapping = None


class StoryboardEntryOrTransition(PropertyGroup):
    

    name = StringProperty(name="name")
    frame_start = IntProperty(name="Start frame")
    frame_end = IntProperty(name="End frame")

    def update_from(self, other) -> None:
        
        self.name = other.name
        self.frame_start = other.frame_start
        self.frame_end = other.frame_end


class Storyboard(PropertyGroup, ListMixin[StoryboardEntry]):
    

    entries = CollectionProperty(type=StoryboardEntry)
    """The entries in this storyboard"""

    entries_or_transitions: bpy_prop_collection[StoryboardEntryOrTransition] = (
        CollectionProperty(type=StoryboardEntryOrTransition)
    )
    """The simplified properties of entries and transitions in this storyboard."""

    active_entry_index: int = IntProperty(
        name="Selected index",
        description="Index of the storyboard entry currently being edited",
    )
    """Index of the active entry (currently being edited) in the storyboard"""

    @property
    def active_entry(self) -> StoryboardEntry | None:
        
        index = self.active_entry_index
        if index is not None and index >= 0 and index < len(self.entries):
            return self.entries[index]
        else:
            return None

    @active_entry.setter
    def active_entry(self, entry: StoryboardEntry | None):
        if entry is None:
            self.active_entry_index = -1
            return

        for i, entry_in_storyboard in enumerate(self.entries):
            if entry_in_storyboard == entry:
                self.active_entry_index = i
                return
        else:
            self.active_entry_index = -1

    @with_context
    def add_new_entry(
        self,
        name: str | None = None,
        frame_start: int | None = None,
        duration: int | None = None,
        *,
        purpose: StoryboardEntryPurpose = StoryboardEntryPurpose.SHOW,
        formation: Collection | None = None,
        select: bool = False,
        context: Context | None = None,
    ) -> StoryboardEntry | None:
        
        assert context is not None

        if name is None:
            if formation is None:
                raise ValueError(
                    "at least one of the name and the formation must be specified"
                )
            name = formation.name

        scene = context.scene
        fps = scene.render.fps
        if frame_start is None:
            frame_start = (
                self.frame_end + fps * DEFAULT_STORYBOARD_TRANSITION_DURATION
                if self.entries
                else scene.frame_start
            )

        if duration is None or duration < 0:
            duration = fps * DEFAULT_STORYBOARD_ENTRY_DURATION

        entry: StoryboardEntry = self.entries.add()
        entry.frame_start = frame_start
        entry.duration = duration
        entry.name = name
        entry.purpose = purpose.name

        if (
            formation is None
            and hasattr(scene, "skybrush")
            and hasattr(scene.skybrush, "formations")
        ):
            
            formation = scene.skybrush.formations.selected
            if self.contains_formation(formation):
                formation = None

        if formation is not None:
            entry.formation = formation

        
        
        name = entry.name
        frame_start = entry.frame_start

        self._sort_entries()

        
        
        
        for entry in self.entries:
            if entry.name == name and entry.frame_start == frame_start:
                break
        else:
            entry = None

        if select:
            self.active_entry = entry

        self._regenerate_entries_or_transitions()

        return entry

    def contains_formation(self, formation) -> bool:
        
        return any(entry.formation == formation for entry in self.entries)

    @property
    def entry_after_active_entry(self) -> StoryboardEntry | None:
        
        index = self.active_entry_index
        if index is not None and index >= 0 and index < len(self.entries) - 1:
            return self.entries[index + 1]
        else:
            return None

    @property
    def entry_before_active_entry(self) -> StoryboardEntry | None:
        
        index = self.active_entry_index
        if index is not None and self.entries and index > 0:
            return self.entries[index - 1]
        else:
            return None

    @property
    def first_entry(self) -> StoryboardEntry | None:
        
        if self.entries:
            return self.entries[0]
        else:
            return None

    @property
    def first_formation(self):
        
        entry = self.first_entry
        return entry.formation if entry else None

    @property
    def frame_end(self) -> int:
        
        return (
            max(entry.frame_end for entry in self.entries)
            if self.entries
            else self.frame_start
        )

    @property
    def frame_start(self) -> int:
        
        return (
            min(entry.frame_start for entry in self.entries)
            if self.entries
            else bpy.context.scene.frame_start
        )

    def get_entry_or_transition_by_name(
        self, name: str
    ) -> StoryboardEntryOrTransition | None:
        
        for entry in self.entries_or_transitions:
            if entry.name == name:
                return entry

    def get_first_entry_for_formation(self, formation) -> StoryboardEntry | None:
        
        for entry in self.entries:
            if entry.formation == formation:
                return entry

    def get_index_of_entry_containing_frame(self, frame: int) -> int:
        
        for index, entry in enumerate(self.entries):
            if entry.contains_frame(frame):
                return index
        return -1

    def get_index_of_entry_after_frame(self, frame: int) -> int:
        
        best_distance, closest = float("inf"), -1
        for index, entry in enumerate(self.entries):
            if entry.frame_start > frame:
                diff = entry.frame_start - frame
                if diff < best_distance:
                    best_distance = diff
                    closest = index

        return closest

    def get_index_of_entry_before_frame(self, frame: int) -> int:
        
        best_distance, closest = float("inf"), -1
        for index, entry in enumerate(self.entries):
            
            
            if entry.frame_end <= frame:
                diff = frame - entry.frame_end
                if diff < best_distance:
                    best_distance = diff
                    closest = index

        return closest

    def get_mapping_at_frame(self, frame: int):
        
        index = self.get_index_of_entry_containing_frame(frame)
        if index >= 0:
            return self.entries[index].get_mapping()

        index = self.get_index_of_entry_before_frame(frame)
        if index >= 0:
            return self.entries[index].get_mapping()

        return None

    def get_formation_status_at_frame(self, frame: int) -> str:
        
        index = self.get_index_of_entry_containing_frame(frame)
        if index >= 0:
            return self.entries[index].name

        index = self.get_index_of_entry_after_frame(frame)
        if index < 0:
            last = self.last_entry
            if last is None:
                return ""

            return "{} ->".format(last.name)

        if index == 0:
            return "-> {}".format(self.entries[index].name)

        return "{} -> {}".format(self.entries[index - 1].name, self.entries[index].name)

    def get_frame_range_of_formation_or_transition_at_frame(
        self, frame: int
    ) -> tuple[int, int] | None:
        
        index = self.get_index_of_entry_containing_frame(frame)
        if index >= 0:
            entry: StoryboardEntry = self.entries[index]
            return entry.frame_start, entry.frame_end

        index = self.get_index_of_entry_after_frame(frame)
        if index > 0:
            return (
                self.entries[index - 1].frame_end,
                self.entries[index].frame_start,
            )
        else:
            return None

    @property
    def last_entry(self) -> StoryboardEntry | None:
        
        if self.entries:
            return self.entries[len(self.entries) - 1]
        else:
            return None

    @property
    def last_formation(self):
        
        entry = self.last_entry
        return entry.formation if entry else None

    def get_transition_duration_into_current_entry(self) -> int:
        
        prev, current = self.entry_before_active_entry, self.active_entry
        if prev is not None and current is not None:
            return current.frame_start - prev.frame_end
        else:
            return 0

    def get_transition_duration_from_current_entry(self) -> int:
        
        current, next = self.active_entry, self.entry_after_active_entry
        if next is not None and current is not None:
            return next.frame_start - current.frame_end
        else:
            return 0

    @property
    def second_entry(self) -> StoryboardEntry | None:
        
        if len(self.entries) > 1:
            return self.entries[1]
        else:
            return None

    def validate_and_sort_entries(self) -> list[StoryboardEntry]:
        
        entries = list(self.entries)
        entries.sort(key=StoryboardEntry.sort_key)

        for validator in (
            self._validate_entry_sequence,
            self._validate_formation_size_contraints,
        ):
            validator(entries)

        active_entry = self.active_entry
        self._sort_entries()
        self.active_entry = active_entry

        self._regenerate_entries_or_transitions()

        
        
        return sorted(self.entries, key=StoryboardEntry.sort_key)

    def _validate_entry_sequence(self, sorted_entries: list[StoryboardEntry]) -> None:
        
        current_purpose = StoryboardEntryPurpose.UNSPECIFIED
        for index, (entry, next_entry) in enumerate(
            zip(sorted_entries, sorted_entries[1:])
        ):
            
            if entry.frame_end >= next_entry.frame_start:
                raise StoryboardValidationError(
                    f"Storyboard entry {entry.name!r} at index {index + 1} and "
                    f"frame {next_entry.frame_start} overlaps with next entry "
                    f"{next_entry.name!r}"
                )

            
            entry_purpose, next_purpose = (
                StoryboardEntryPurpose[entry.purpose],
                StoryboardEntryPurpose[next_entry.purpose],
            )
            if entry_purpose != StoryboardEntryPurpose.UNSPECIFIED:
                current_purpose = entry_purpose
            if (
                next_purpose != StoryboardEntryPurpose.UNSPECIFIED
                and next_purpose.order < current_purpose.order
            ):
                raise StoryboardValidationError(
                    f"Storyboard entry #{index + 1} has purpose "
                    f"{next_purpose.ui_name!r} that cannot be after "
                    f"previous entry with purpose {current_purpose.ui_name!r}"
                )

    def _validate_formation_size_contraints(
        self, sorted_entries: list[StoryboardEntry]
    ) -> None:
        
        drones = Collections.find_drones(create=False)
        num_drones = len(drones.objects) if drones else 0
        for entry in sorted_entries:
            formation = entry.formation
            if formation is None:
                continue

            num_markers = count_markers_in_formation(formation)
            if num_markers > num_drones:
                if num_drones > 1:
                    msg = f"you only have {num_drones} drones"
                elif num_drones == 1:
                    msg = "you only have one drone"
                else:
                    msg = "you have no drones"
                raise StoryboardValidationError(
                    f"Storyboard entry {entry.name!r} contains a formation with {num_markers} drones but {msg}"
                )

    def _on_active_entry_moving_down(self, this_entry, next_entry) -> bool:
        pad = next_entry.frame_start - this_entry.frame_end

        this_entry.frame_start, next_entry.frame_start = (
            this_entry.frame_start + next_entry.duration + pad,
            this_entry.frame_start,
        )

        return True

    def _on_active_entry_moving_up(self, this_entry, prev_entry) -> bool:
        pad = this_entry.frame_start - prev_entry.frame_end

        this_entry.frame_start, prev_entry.frame_start = (
            prev_entry.frame_start,
            prev_entry.frame_start + this_entry.duration + pad,
        )

        return True

    def _sort_entries(self) -> None:
        
        
        sort_collection(self.entries, key=StoryboardEntry.sort_key)

    def _regenerate_entries_or_transitions(self) -> None:
        
        self.entries_or_transitions.clear()
        for prev, next in consecutive_pairs(self.entries):
            
            item = self.entries_or_transitions.add()
            item.name = prev.name
            item.frame_start = prev.frame_start
            item.frame_end = prev.frame_end
            
            item = self.entries_or_transitions.add()
            item.name = f"{prev.name} -> {next.name}"
            item.frame_start = prev.frame_end
            item.frame_end = next.frame_start
        
        if self.last_entry:
            item = self.entries_or_transitions.add()
            item.name = self.last_entry.name
            item.frame_start = self.last_entry.frame_start
            item.frame_end = self.last_entry.frame_end

        
        
        bpy.context.scene.skybrush.light_effects.update_from_storyboard(bpy.context)


@with_context
def get_storyboard(*, context: Context | None = None) -> Storyboard:
    
    assert context is not None
    return context.scene.skybrush.storyboard
