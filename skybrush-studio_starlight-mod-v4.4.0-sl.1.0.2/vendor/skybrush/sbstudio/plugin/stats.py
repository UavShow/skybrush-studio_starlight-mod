from sbstudio.plugin.constants import Collections

__all__ = ("get_drone_count",)


def get_drone_count() -> int:
    
    drones = Collections.find_drones(create=False)
    return 0 if drones is None else len(drones.objects)
