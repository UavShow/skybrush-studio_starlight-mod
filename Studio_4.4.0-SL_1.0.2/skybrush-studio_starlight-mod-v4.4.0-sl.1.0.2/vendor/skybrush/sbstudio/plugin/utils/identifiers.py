from itertools import count as count_from

import bpy

__all__ = ("create_internal_id", "is_internal_id", "propose_name", "propose_names")


def create_internal_id(name: str) -> str:
    
    return f"Skybrush[{name}]"


def is_internal_id(name: str) -> bool:
    
    return name.startswith("Skybrush[") and name.endswith("]")


def propose_name(template: str, *, for_collection: bool = False) -> str:
    
    return propose_names(template, 1, for_collection=for_collection)[0]


def propose_names(
    template: str, count: int, *, for_collection: bool = False
) -> list[str]:
    
    if count <= 0:
        return []

    coll = bpy.data.collections if for_collection else bpy.data.objects
    result = []

    if "{}" not in template:
        
        try:
            coll[template]
        except KeyError:
            
            result.append(template)

        template = template + " {}"

    if len(result) < count:
        for index in count_from(1):
            candidate = template.format(index)
            try:
                coll[candidate]
            except KeyError:
                
                result.append(candidate)
                if len(result) >= count:
                    break

    return result
