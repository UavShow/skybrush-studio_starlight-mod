import bpy
from bpy.types import Material

from sbstudio.model.types import RGBAColor

from .errors import SkybrushStudioAddonError

__all__ = (
    "create_colored_material",
    "create_glowing_material",
    "get_material_for_led_light_color",
    "get_material_for_pyro",
    "set_emission_strength_of_material",
)

is_blender_6_or_later = bpy.app.version >= (6, 0, 0)


def _create_material(name: str):
    
    mat = bpy.data.materials.new(name)

    
    if not is_blender_6_or_later:
        mat.use_nodes = True

    return mat


def _find_shader_node_by_name_and_type(material, name: str, type: str):
    
    nodes = material.node_tree.nodes

    try:
        node = nodes[name]
        if node.type == type:
            return node
    except KeyError:
        pass

    
    for node in nodes:
        if node.type == type:
            return node

    raise KeyError(f"no shader node with type {type!r} in material")


def create_colored_material(name: str, color: RGBAColor):
    
    mat = _create_material(name)
    _set_diffuse_color_of_material(mat, color)
    _set_specular_reflection_intensity_of_material(mat, 0)
    return mat


def create_glowing_material(
    name: str, color: RGBAColor = (1.0, 1.0, 1.0, 1.0), strength: float = 1.0
):
    
    mat = _create_material(name)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    links.clear()
    nodes.clear()

    object_info_node = nodes.new("ShaderNodeObjectInfo")
    object_info_node.location = (-300, 0)

    emission_node = nodes.new("ShaderNodeEmission")
    emission_node.inputs["Strength"].default_value = strength
    emission_node.location = (0, 0)

    output_node = nodes.new("ShaderNodeOutputMaterial")
    output_node.location = (300, 0)

    links.new(object_info_node.outputs["Color"], emission_node.inputs["Color"])
    links.new(emission_node.outputs["Emission"], output_node.inputs["Surface"])

    _set_diffuse_color_of_material(mat, color)

    return mat


def get_material_for_led_light_color(drone) -> Material | None:
    
    if len(drone.material_slots) > 0:
        return drone.material_slots[0].material
    else:
        return None


def get_material_for_pyro(drone) -> Material | None:
    
    if len(drone.material_slots) > 1:
        return drone.material_slots[1].material
    else:
        return None


def _set_diffuse_color_of_material(material, color: RGBAColor):
    
    if material.use_nodes:
        
        
        
        _, input = _get_shader_node_and_input_for_diffuse_color_of_material(material)
        input.default_value = color

    material.diffuse_color = color


def set_emission_strength_of_material(material, value: float) -> None:
    
    if not material.use_nodes:
        return

    try:
        node = _find_shader_node_by_name_and_type(material, "Emission", "EMISSION")
        input = node.inputs["Strength"]
    except KeyError:
        return

    input.default_value = value


def _get_shader_node_and_input_for_diffuse_color_of_material(material):
    
    try:
        node = _find_shader_node_by_name_and_type(material, "Emission", "EMISSION")
        input = node.inputs["Color"]
        return node, input
    except KeyError:
        try:
            node = _find_shader_node_by_name_and_type(
                material, "Principled BSDF", "BSDF_PRINCIPLED"
            )
            input = node.inputs["Base Color"]
            return node, input
        except KeyError:
            try:
                node = _find_shader_node_by_name_and_type(
                    material, "Principled BSDF", "BSDF_PRINCIPLED"
                )
                input = node.inputs["Emission Color"]
                return node, input
            except KeyError:
                raise SkybrushStudioAddonError(
                    "Material does not have a diffuse color shader node"
                ) from None


def _set_specular_reflection_intensity_of_material(material, intensity):
    
    material.specular_intensity = intensity
    node = _find_shader_node_by_name_and_type(
        material, "Principled BSDF", "BSDF_PRINCIPLED"
    )
    node.inputs["Specular IOR Level"].default_value = intensity
