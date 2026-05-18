from bpy.types import Material, Operator

from sbstudio.plugin.constants import Collections, Templates
from sbstudio.plugin.materials import (
    create_colored_material,
    get_material_for_pyro,
)

__all__ = ("DetachMaterialsFromDroneTemplateOperator",)


def detach_pyro_material_from_drone_template(
    drone, template_material: Material | None = None
) -> None:
    if template_material is None:
        template = Templates.find_drone(create=False)
        if template:
            template_material = get_material_for_pyro(template)
            
            
            
            if template_material is None:
                template_material = create_colored_material(
                    "Drone pyro template material", color=(1.0, 1.0, 1.0, 1.0)
                )
                template.data.materials.append(template_material)

    if template_material is None:
        return None

    
    
    
    if get_material_for_pyro(drone) is None:
        drone.data.materials.append(template_material)

    for slot in drone.material_slots:
        if slot.material == template_material:
            copied_material = template_material.copy()
            copied_material.name = f"Pyro of {drone.name}"
            slot.material = copied_material
            return slot.material


class DetachMaterialsFromDroneTemplateOperator(Operator):
    

    bl_idname = "skybrush.detach_materials_from_drone_template"
    bl_label = "Detach Materials from Drone Template"

    def execute(self, context):
        template = Templates.find_drone(create=False)
        pyro_template_material = get_material_for_pyro(template) if template else None

        drones = Collections.find_drones()
        for drone in drones.objects:
            detach_pyro_material_from_drone_template(
                drone, template_material=pyro_template_material
            )

        return {"FINISHED"}
