__all__ = (
    "format_latitude",
    "format_longitude",
    "parse_latitude",
    "parse_longitude",
)


def format_latitude(latitude: float) -> str:
    
    if latitude < 0:
        return f"S {round(-latitude, ndigits=7)}\u00b0"
    else:
        return f"N {round(latitude, ndigits=7)}\u00b0"


def format_longitude(longitude: float) -> str:
    
    if longitude < 0:
        return f"W {round(-longitude, ndigits=7)}\u00b0"
    else:
        return f"E {round(longitude, ndigits=7)}\u00b0"


def _parse_coordinate_from_string(input: str, positive: str, negative: str) -> float:
    input = input.strip().upper()
    sign = 1

    if input[0] == positive:
        input = input[1:]
    elif input[-1] == positive:
        input = input[:-1]
    elif input[0] == negative:
        sign = -1
        input = input[1:]
    elif input[-1] == negative:
        sign = -1
        input = input[:-1]

    input = input.strip().removesuffix("\u00b0")
    try:
        retval = float(input) * sign
    except ValueError:
        retval = 0

    return retval


def parse_latitude(latitude: str | float) -> float:
    

    if isinstance(latitude, str):
        latitude = _parse_coordinate_from_string(latitude, "N", "S")

    latitude = max(-90, min(90, latitude))

    return latitude


def parse_longitude(longitude: str | float) -> float:
    

    if isinstance(longitude, str):
        longitude = _parse_coordinate_from_string(longitude, "E", "W")

    longitude = max(-180, min(180, longitude))

    return longitude
