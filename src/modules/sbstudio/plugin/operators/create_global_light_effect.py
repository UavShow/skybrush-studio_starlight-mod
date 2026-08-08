from .base import LightEffectOperator

__all__ = ("CreateOrSelectGlobalLightEffectOperator",)


class CreateOrSelectGlobalLightEffectOperator(LightEffectOperator):
    """Blender operator that creates the unique global transition light
    effect, or selects it if one already exists.
    """

    bl_idname = "skybrush.create_or_select_global_light_effect"
    bl_label = "Global Transition Light Effect"
    bl_description = (
        "Creates the unique global transition light effect that is applied "
        "automatically to any part of the timeline not covered by another "
        "light effect, or selects it if one already exists."
    )

    def execute_on_light_effect_collection(self, light_effects, context):
        light_effects.get_or_create_global_transition_entry(select=True)
        return {"FINISHED"}
