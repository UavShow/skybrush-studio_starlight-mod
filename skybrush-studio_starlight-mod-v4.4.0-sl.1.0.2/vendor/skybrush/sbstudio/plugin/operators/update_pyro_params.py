from bpy.types import Operator

from sbstudio.plugin.selection import get_selected_drones
from sbstudio.plugin.utils.pyro_markers import get_pyro_markers_of_object
from sbstudio.plugin.views import find_all_3d_views_and_their_areas

__all__ = ("UpdatePyroParamsFromSelectedDroneOperator",)


class UpdatePyroParamsFromSelectedDroneOperator(Operator):
    

    bl_idname = "skybrush.update_pyro_params_from_selection"
    bl_label = "Update Pyro Params from Selected Drone"
    bl_description = (
        "Updates the pyro parameters from the currently selected drone and pyro channel"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        
        return {"FINISHED"} if self._run(context) else {"CANCELLED"}

    def _run(self, context):
        
        selection = get_selected_drones()
        if len(selection) != 1:
            self.report({"ERROR"}, "Select a single drone to update pyro params")
            return False
        drone = selection[0]

        
        pyro_control = context.scene.skybrush.pyro_control
        channel = pyro_control.channel

        
        marker = get_pyro_markers_of_object(drone).markers.get(channel)
        if marker is None:
            self.report(
                {"ERROR"},
                f"The selected drone does not trigger pyro on channel {channel}",
            )
            return False

        
        pyro_control.update_params_from_pyro_payload(marker.payload)

        
        for _, area in find_all_3d_views_and_their_areas():
            area.tag_redraw()

        return True
