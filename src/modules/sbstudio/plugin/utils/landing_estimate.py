"""Utilities for estimating real-world drone landing times in RTL mode.

Real firmware (tested against firmware 4.4.4) performs the final touchdown
after a Return-To-Launch mode switch using its own two-stage descent speed
profile; that part of the flight is generally *not* animated in Blender
(the animation typically ends at a safe altitude and lets the flight
controller finish the landing on its own). These helpers estimate how long
that takes in real life, and manage a localized timeline marker that
communicates the estimated real landing moment to the user.
"""

import bpy
from bpy.types import Context

from sbstudio.i18n.translations import translations_dict

__all__ = (
    "RTL_MODE_SWITCH_DELAY",
    "LAND_SPEED_HIGH",
    "LAND_SPEED_LOW",
    "LAND_ALT_LOW",
    "estimate_real_landing_duration",
    "get_localized_marker_name",
    "get_all_localized_marker_names",
    "place_landed_time_marker",
)

# Real firmware (4.4.4) RTL landing parameters, used only to *estimate* the
# real-world moment at which a drone actually touches down after the
# animation ends (this part of the flight is not animated in Blender).
RTL_MODE_SWITCH_DELAY = 3.0  # s; motionless hover right after the RTL switch
LAND_SPEED_HIGH = 1.3  # m/s; descent speed above LAND_ALT_LOW
LAND_SPEED_LOW = 0.4  # m/s; descent speed at/below LAND_ALT_LOW
LAND_ALT_LOW = 1.0  # m; altitude below which the firmware switches to LAND_SPEED_LOW


def estimate_real_landing_duration(altitude: float) -> float:
    """Estimates how long it takes, in real life, for a drone in RTL mode to
    descend from ``altitude`` (in meters) all the way to the ground, using
    the firmware's two-stage descent speed profile (fast descent above
    ``LAND_ALT_LOW``, slow descent at/below it). Does *not* include the
    RTL mode-switch hover; add ``RTL_MODE_SWITCH_DELAY`` separately.
    """
    if altitude <= LAND_ALT_LOW:
        return altitude / LAND_SPEED_LOW
    return (altitude - LAND_ALT_LOW) / LAND_SPEED_HIGH + LAND_ALT_LOW / LAND_SPEED_LOW


def get_localized_marker_name(msgid: str) -> str:
    """Returns ``msgid`` translated into Blender's currently active interface
    language (falls back to English if no translation is available or
    interface translation is disabled).
    """
    return bpy.app.translations.pgettext_iface(msgid)


def get_all_localized_marker_names(msgid: str) -> set[str]:
    """Returns every known localized variant of ``msgid`` (across all
    languages we have a translation for), so that a marker created in a
    previous run -- possibly under a different Blender language -- can
    still be found and replaced.
    """
    names = {msgid}
    for lang_dict in translations_dict.values():
        translated = lang_dict.get(("*", msgid))
        if translated:
            names.add(translated)
    return names


def place_landed_time_marker(context: Context, msgid: str, *, frame: int) -> None:
    """Creates a timeline marker named after ``msgid`` (localized to
    Blender's current interface language) at the given ``frame``, replacing
    any marker previously created for the same ``msgid`` regardless of which
    language it was created under.
    """
    timeline_markers = context.scene.timeline_markers
    known_names = get_all_localized_marker_names(msgid)
    for existing_marker in [m for m in timeline_markers if m.name in known_names]:
        timeline_markers.remove(existing_marker)
    timeline_markers.new(get_localized_marker_name(msgid), frame=frame)
