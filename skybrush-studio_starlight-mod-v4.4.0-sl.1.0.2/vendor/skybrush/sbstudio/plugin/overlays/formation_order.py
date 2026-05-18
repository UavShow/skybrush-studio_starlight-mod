import bpy
import gpu
import gpu.state
from gpu_extras.batch import batch_for_shader
from numpy import linspace

from sbstudio.plugin.model.formation import (
    get_world_coordinates_of_markers_from_formation,
)

from .base import ShaderOverlay

__all__ = ("FormationOrderOverlay",)


class FormationOrderOverlay(ShaderOverlay):
    

    shader_type = "SMOOTH_COLOR"

    def draw_3d(self) -> None:
        gpu.state.blend_set("ALPHA")

        
        
        
        batch = self._create_shader_batch()

        if batch:
            assert self._shader is not None

            self._shader.bind()
            gpu.state.line_width_set(3)
            batch.draw(self._shader)

    def _create_shader_batch(self):
        try:
            formation = bpy.context.scene.skybrush.formations.selected
        except Exception:
            formation = None

        if formation:
            assert self._shader is not None

            coords = get_world_coordinates_of_markers_from_formation(formation).tolist()

            
            colors = [(frac, 1 - frac, 0, 1) for frac in linspace(0, 1, len(coords))]
            return batch_for_shader(
                self._shader, "LINE_STRIP", {"pos": coords, "color": colors}
            )
