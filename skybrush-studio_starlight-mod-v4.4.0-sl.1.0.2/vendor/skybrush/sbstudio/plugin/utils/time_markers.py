from bpy.types import Context

from sbstudio.model.time_markers import TimeMarkers

__all__ = ("get_time_markers_from_context",)


def get_time_markers_from_context(context: Context) -> TimeMarkers:
    
    fps = context.scene.render.fps
    markers = context.scene.timeline_markers
    scene_settings = getattr(context.scene.skybrush, "settings", None)
    
    our_marker_names_as_string = (
        scene_settings.time_markers
        if scene_settings and scene_settings.time_markers
        else [marker.name for marker in markers]
    )
    
    our_markers = {
        marker.name: marker.frame / fps
        for marker in markers
        if marker.name in our_marker_names_as_string
    }

    return TimeMarkers(markers=our_markers)
