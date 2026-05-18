from typing import Any

from bpy.props import FloatVectorProperty

__all__ = ("ColorProperty",)


def ColorProperty(**kwds):
    
    props: dict[str, Any] = {"default": (1.0, 1.0, 1.0)}
    props.update(kwds)
    props.update(subtype="COLOR", min=0.0, max=1.0)
    return FloatVectorProperty(**props)
