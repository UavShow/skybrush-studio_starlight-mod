from typing import Any

from bpy.props import EnumProperty
from bpy.types import Context

from sbstudio.plugin.utils import with_context

__all__ = ("FrameRangeProperty",)


def FrameRangeProperty(**kwds):
    
    props: dict[str, Any] = {
        "name": "Frame range",
        "description": "Choose a frame range to use for this operation",
        "items": (
            ("STORYBOARD", "Storyboard", "Use the storyboard to define frame range"),
            ("RENDER", "Render", "Use global render frame range set by scene"),
            ("PREVIEW", "Preview", "Use global preview frame range set by scene"),
            (
                "AROUND_CURRENT_FRAME",
                "Current formation or transition",
                "Use the formation or transition containing the current frame",
            ),
        ),
        "default": "STORYBOARD",
    }
    props.update(kwds)
    return EnumProperty(**props)


@with_context
def resolve_frame_range(
    range: str, *, context: Context | None = None
) -> tuple[int, int] | None:
    
    from sbstudio.plugin.model.storyboard import get_storyboard

    assert context is not None  

    if range == "RENDER":
        
        return (context.scene.frame_start, context.scene.frame_end)
    elif range == "PREVIEW":
        
        return (context.scene.frame_preview_start, context.scene.frame_preview_end)
    elif range == "STORYBOARD":
        
        storyboard = get_storyboard(context=context)
        return (storyboard.frame_start, storyboard.frame_end)
    elif range == "AROUND_CURRENT_FRAME":
        
        
        storyboard = get_storyboard(context=context)
        return storyboard.get_frame_range_of_formation_or_transition_at_frame(
            context.scene.frame_current
        )
    else:
        raise RuntimeError(f"Unknown frame range: {range!r}")
