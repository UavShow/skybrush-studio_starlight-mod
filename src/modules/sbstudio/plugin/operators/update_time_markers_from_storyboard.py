from json import dumps, loads
import bpy
from bpy.app.translations import pgettext_iface

from sbstudio.plugin.utils.collections import filter_collection

from .base import StoryboardOperator

__all__ = ("UpdateTimeMarkersFromStoryboardOperator",)

_marker_language_state = {}


def _refresh_enhanced_marker_language():
    context = bpy.context
    scene = context.scene
    if scene is None or not hasattr(scene, "skybrush"):
        return 1.0
    if context.window_manager and context.window_manager.is_interface_locked:
        return 1.0
    view = context.preferences.view
    signature = (view.language, view.use_translate_interface)
    key = scene.as_pointer()
    if _marker_language_state.get(key) == signature:
        return 1.0
    from sbstudio.plugin.model.storyboard import get_storyboard
    storyboard = get_storyboard(context=context)
    if any(e.formation is not None and "enhanced_rth_core" in e.formation
           for e in storyboard.entries):
        if not bpy.ops.skybrush.update_time_markers_from_storyboard.poll():
            return 1.0
        bpy.ops.skybrush.update_time_markers_from_storyboard()
    _marker_language_state[key] = signature
    return 1.0


def register_marker_language_sync():
    _marker_language_state.clear()
    if not bpy.app.timers.is_registered(_refresh_enhanced_marker_language):
        bpy.app.timers.register(_refresh_enhanced_marker_language,
                                first_interval=1.0, persistent=True)


def unregister_marker_language_sync():
    if bpy.app.timers.is_registered(_refresh_enhanced_marker_language):
        bpy.app.timers.unregister(_refresh_enhanced_marker_language)
    _marker_language_state.clear()


class UpdateTimeMarkersFromStoryboardOperator(StoryboardOperator):


    bl_idname = "skybrush.update_time_markers_from_storyboard"
    bl_label = "Update Time Markers from Storyboard"
    bl_description = "Update all time markers to be synchronized with the storyboard"

    def execute_on_storyboard(self, storyboard, context):
        our_marker_names: list[str] | None = None

        scene = context.scene

        markers = scene.timeline_markers
        our_marker_names_as_string = scene.skybrush.settings.time_markers
        if our_marker_names_as_string:
            try:
                our_marker_names = loads(our_marker_names_as_string)
            except Exception:

                pass

        if our_marker_names is not None:

            is_not_our_marker = lambda marker: marker.name not in our_marker_names
            filter_collection(markers, is_not_our_marker)
        else:
            markers.clear()

        our_marker_names = []
        landing_entries = [entry for entry in storyboard.entries
                           if entry.formation is not None and
                           "rtl_landing_delay_frames" in entry.formation]
        last_landing_entry = landing_entries[-1] if landing_entries else None
        grid_entries = [entry for entry in storyboard.entries
                        if entry.formation is not None and
                        "grid_arrival_offset" in entry.formation]
        last_grid_entry = grid_entries[-1] if grid_entries else None
        for entry in storyboard.entries:
            enhanced = entry.formation is not None and "enhanced_rth_core" in entry.formation
            marker_name = (pgettext_iface("Return to Aerial Grid (Direct) starts", "EnhancedRTH")
                           if enhanced else "at {}".format(entry.name))
            if enhanced and entry != last_grid_entry:
                marker_name = "{} {}".format(entry.name, marker_name)
            our_marker_names.append(marker_name)
            markers.new(marker_name, frame=entry.frame_start)

            formation = entry.formation
            if formation is not None and "grid_arrival_offset" in formation:
                title = pgettext_iface("Grid assembled", "EnhancedRTH")
                marker_name = title if entry == last_grid_entry else "{} {}".format(entry.name, title)
                our_marker_names.append(marker_name)
                markers.new(marker_name, frame=entry.frame_start +
                            int(formation["grid_arrival_offset"]))

            if formation is not None and "rtl_landing_delay_frames" in formation:
                title = pgettext_iface("All drones landed", "EnhancedRTH")
                marker_name = title if entry == last_landing_entry else "{} {}".format(entry.name, title)
                our_marker_names.append(marker_name)
                markers.new(marker_name, frame=entry.frame_end +
                            int(formation["rtl_landing_delay_frames"]))

            if entry.duration > 0:
                marker_name = (pgettext_iface("Return to Aerial Grid (Direct) ends", "EnhancedRTH")
                               if enhanced else "{} ends".format(entry.name))
                if enhanced and entry != last_grid_entry:
                    marker_name = "{} {}".format(entry.name, marker_name)
                our_marker_names.append(marker_name)
                markers.new(
                    marker_name,
                    frame=entry.frame_start + entry.duration,
                )

        try:
            scene.skybrush.settings.time_markers = dumps(our_marker_names)
        except Exception:

            pass

        return {"FINISHED"}
