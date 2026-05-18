import json
import logging
import re
from base64 import b64encode
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from gzip import compress
from http import HTTPStatus
from http.client import HTTPResponse
from io import IOBase, TextIOWrapper
from pathlib import Path
from shutil import copyfileobj
from ssl import CERT_NONE, create_default_context
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from natsort import natsorted

from sbstudio.model.cameras import Camera
from sbstudio.model.color import Color3D
from sbstudio.model.light_program import LightProgram
from sbstudio.model.location import ShowLocation
from sbstudio.model.point import Point3D
from sbstudio.model.pyro_markers import PyroMarkers
from sbstudio.model.safety_check import SafetyCheckParams
from sbstudio.model.time_markers import TimeMarkers
from sbstudio.model.trajectory import Trajectory
from sbstudio.model.types import Coordinate3D
from sbstudio.model.yaw import YawSetpointList
from sbstudio.utils import create_path_and_open

from .constants import COMMUNITY_SERVER_URL
from .errors import SkybrushStudioAPIError
from .types import Limits, Mapping, SmartRTHPlan, TransitionPlan, Version

__all__ = ("SkybrushStudioAPI",)


log = logging.getLogger(__name__)


class Response:
    

    def __init__(self, response: HTTPResponse):
        
        self._response = response

    @property
    def content_type(self) -> str:
        
        info = self._response.info()
        return info.get_content_type()

    def _run_sanity_checks(self) -> None:
        
        status_code = self._response.getcode()
        if status_code != 200:
            raise SkybrushStudioAPIError(
                f"Request returned HTTP error code {status_code}"
            )

        if self.content_type not in (
            "application/octet-stream",
            "application/json",
            "application/zip",
        ):
            raise SkybrushStudioAPIError(
                f"Unexpected content type {self.content_type!r} in response"
            )

    def as_bytes(self) -> bytes:
        
        if self.content_type not in ("application/octet-stream", "application/zip"):
            raise SkybrushStudioAPIError("Response type is not an octet stream")
        return self._response.read()

    def as_file_object(self) -> IOBase:
        
        return self._response

    def as_json(self):
        
        if self.content_type != "application/json":
            raise SkybrushStudioAPIError("Response type is not JSON")
        return json.load(TextIOWrapper(self._response, encoding="utf-8"))

    def as_str(self) -> str:
        
        if self.content_type not in (
            "application/octet-stream",
            "application/json",
            "application/zip",
            "text/plain",
        ):
            raise SkybrushStudioAPIError("Invalid response type")

        data = self._response.read()
        if isinstance(data, bytes):
            data = data.decode("utf-8")

        return data

    def save_to_file(self, filename: Path) -> None:
        
        with create_path_and_open(filename, "wb") as f:
            copyfileobj(self._response, f)


_API_KEY_REGEXP = re.compile(r"^[a-zA-Z0-9-_.]*$")
_LICENSE_API_KEY_REGEXP = re.compile(
    r"^License [A-Za-z0-9+/=]{4,}([A-Za-z0-9+/=]{2})*$"
)


class SkybrushStudioAPI:
    

    _api_key: str | None = None
    """The API key that will be submitted with each request. For license-type
    API keys, the key must start with the string "License ".
    """

    _root: str
    """The root URL of the API, with a trailing slash"""

    _http_status: dict[int | None, str]
    """Predefined HTTP status messages."""

    @staticmethod
    def validate_api_key(key: str) -> str:
        
        if key.startswith("License"):
            if not _LICENSE_API_KEY_REGEXP.match(key):
                raise ValueError("Invalid license-type API key")
        else:
            if not _API_KEY_REGEXP.match(key):
                raise ValueError("Invalid API key")
        return key

    def __init__(
        self,
        url: str = COMMUNITY_SERVER_URL,
        api_key: str | None = None,
        license_file: str | None = None,
    ):
        
        self._root = None  
        self._request_context = create_default_context()
        self._http_status = {status.value: status.phrase for status in HTTPStatus}
        self._http_status[None] = "HTTP error"

        if api_key and license_file:
            raise SkybrushStudioAPIError(
                "Cannot use API key and license file at the same time"
            )

        if license_file:
            self.api_key = self._convert_license_file_to_api_key(license_file)
        else:
            self.api_key = api_key

        self.url = url

    @property
    def api_key(self) -> str | None:
        
        return self._api_key

    @api_key.setter
    def api_key(self, value: str | None) -> None:
        self._api_key = self.validate_api_key(value) if value else None

    def _convert_license_file_to_api_key(self, file: str) -> str:
        
        if not Path(file).exists():
            raise ValueError("License file does not exist")

        try:
            with open(file, "rb") as fp:
                api_key = f"License {b64encode(fp.read()).decode('ascii')}"
        except Exception:
            raise ValueError("Could not read license file") from None

        return api_key

    @property
    def url(self) -> str:
        
        return self._root

    @url.setter
    def url(self, value: str) -> None:
        if not value.endswith("/"):
            value += "/"
        self._root = value

    @contextmanager
    def _send_request(self, url: str, data: Any = None) -> Iterator[Response]:
        
        content_type = None
        content_encoding = None

        if data is None:
            method = "GET"
        else:
            method = "POST"
            if not isinstance(data, bytes):
                data = json.dumps(data).encode("utf-8")
                content_type = "application/json"
                content_encoding = "gzip"
            else:
                content_type = "application/octet-stream"

        if content_encoding == "gzip":
            data = compress(data)

        headers = {}
        if content_type is not None:
            headers["Content-Type"] = content_type
        if content_encoding is not None:
            headers["Content-Encoding"] = content_encoding
        if self._api_key is not None:
            headers["X-Skybrush-API-Key"] = self._api_key

        url = urljoin(self._root, url.lstrip("/"))
        req = Request(url, data=data, headers=headers, method=method)

        try:
            with urlopen(req, context=self._request_context) as raw_response:
                response = Response(raw_response)
                response._run_sanity_checks()
                yield response
        except HTTPError as ex:
            
            
            if ex.status in (400, 403, 500):
                try:
                    body = ex.read().decode("utf-8")
                except Exception:
                    
                    
                    body = "{}"
                try:
                    decoded_body = json.loads(body)
                except Exception:
                    
                    
                    decoded_body = {}
                if isinstance(decoded_body, dict) and decoded_body.get("detail"):
                    detail = str(decoded_body.get("detail"))
                    raise SkybrushStudioAPIError(
                        f"{self._http_status[ex.status]}: {detail}"
                    ) from None
            elif ex.status == 413:
                
                raise SkybrushStudioAPIError(
                    "You have reached the limits of the community server. "
                    "Consider purchasing a license for a local instance of "
                    "Skybrush Studio Server."
                ) from None

            
            raise SkybrushStudioAPIError(
                f"{self._http_status[ex.status]} ({ex.status}). "
                f"This is most likely a server-side issue; please contact us and let us know."
            ) from ex

    def _skip_ssl_checks(self) -> None:
        
        ctx = create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = CERT_NONE
        self._request_context = ctx

    def decompose_points(
        self,
        points: Sequence[Coordinate3D],
        *,
        min_distance: float,
        method: str = "greedy",
    ) -> list[int]:
        
        data = {
            "version": 1,
            "method": str(method),
            "min_distance": float(min_distance),
            "points": points,
        }
        with self._send_request("operations/decompose", data) as response:
            result = response.as_json()

        if result.get("version") != 1:
            raise SkybrushStudioAPIError("invalid response version")

        return result.get("groups")

    def export(
        self,
        *,
        validation: SafetyCheckParams,
        trajectories: dict[str, Trajectory],
        lights: dict[str, LightProgram] | None = None,
        pyro_programs: dict[str, PyroMarkers] | None = None,
        yaw_setpoints: dict[str, YawSetpointList] | None = None,
        output: Path | None = None,
        show_title: str | None = None,
        show_type: str = "outdoor",
        show_location: ShowLocation | None = None,
        show_segments: dict[str, tuple[float, float]] | None = None,
        ndigits: int = 3,
        timestamp_offset: float | None = None,
        time_markers: TimeMarkers | None = None,
        cameras: list[Camera] | None = None,
        renderer: str | list[str] = "skyc",
        renderer_params: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> bytes | None:
        

        meta = {}
        if show_title is not None:
            meta["title"] = show_title

        if timestamp_offset is not None:
            meta["timestampOffset"] = timestamp_offset

        if show_segments is not None:
            meta["segments"] = show_segments

        if lights is None:
            lights = {name: LightProgram() for name in trajectories.keys()}

        environment: dict[str, Any] = {"type": show_type}

        if cameras:
            environment["cameras"] = [
                camera.as_dict(ndigits=ndigits) for camera in cameras
            ]

        if show_location:
            environment["location"] = show_location.json

        if time_markers is None:
            time_markers = TimeMarkers()

        

        def format_drone(name: str):
            settings = {
                "name": name,
                "lights": lights[name].as_dict(ndigits=ndigits),
                "trajectory": trajectories[name].as_dict(ndigits=ndigits),
            }

            if pyro_programs is not None:
                import bpy

                fps = bpy.context.scene.render.fps

                settings["pyro"] = pyro_programs[name].as_api_dict(
                    fps=fps, ndigits=ndigits
                )
            if yaw_setpoints is not None:
                settings["yawControl"] = yaw_setpoints[name].as_dict(ndigits=ndigits)

            return {"type": "generic", "settings": settings}

        data: dict[str, Any] = {
            "input": {
                "format": "json",
                "data": {
                    "version": 1,
                    "environment": environment,
                    "settings": {
                        "cues": time_markers.as_dict(ndigits=ndigits),
                        "validation": validation.as_dict(ndigits=ndigits),
                    },
                    "swarm": {
                        "drones": [
                            format_drone(name)
                            for name in natsorted(trajectories.keys())
                        ]
                    },
                    "meta": meta,
                },
            },
        }

        if isinstance(renderer, (list, tuple)):
            operation = "multi-render"
            if renderer_params is None:
                renderer_params = [None] * len(renderer)  
            assert isinstance(renderer_params, (list, tuple))
            data["outputs"] = [
                {"format": format, "parameters": parameters or {}}
                for format, parameters in zip(renderer, renderer_params, strict=True)
            ]
        else:
            operation = "render"
            data["output"] = {}
            data["output"]["format"] = renderer
            if renderer_params is not None:
                data["output"]["parameters"] = renderer_params

        with self._send_request(f"operations/{operation}", data) as response:
            if output:
                response.save_to_file(output)
            else:
                return response.as_bytes()

    def convert_show_to_csv(
        self,
        filename: str,
        importer: str,
        *,
        fps: int = 5,
    ) -> bytes:
        

        with open(filename, "rb") as zip_file:
            input_data = b64encode(zip_file.read()).decode("ascii")

        data = {
            "input": {
                "format": importer,
                "data": input_data,
                "parameters": {"simplify": False},
            },
            "output": {
                "format": "csv",
                "parameters": {"fps": fps},
            },
        }

        with self._send_request("operations/render", data) as response:
            result = response.as_bytes()

        return result

    def create_formation_from_svg(
        self,
        source: str,
        num_points: int,
        size: float,
        angle: float,
    ) -> tuple[list[Point3D], list[Color3D]]:
        
        data = {
            "version": 1,
            "method": "svg",
            "parameters": {
                "version": 1,
                "source": source,
                "n": num_points,
                "size": size,
                "angle": angle,
            },
        }

        with self._send_request("operations/create-static-formation", data) as response:
            result = response.as_json()

        if result.get("version") != 1:
            raise SkybrushStudioAPIError("invalid response version")

        points = [Point3D(*point) for point in result.get("points")]
        colors = [Color3D(*color) for color in result.get("colors")]

        return points, colors

    def generate_plots(
        self,
        trajectories: dict[str, Trajectory],
        output: Path,
        validation: SafetyCheckParams,
        plots: Sequence[str] = ("stats", "pos", "vel", "drift", "nn"),
        fps: float = 4,
        ndigits: int = 3,
        time_markers: TimeMarkers | None = None,
    ) -> None:
        
        log.warning("api.generate_plots() is deprecated, use api.export() instead")

        if time_markers is None:
            time_markers = TimeMarkers()

        data = {
            "input": {
                "format": "json",
                "data": {
                    "version": 1,
                    "settings": {
                        "cues": time_markers.as_dict(ndigits=ndigits),
                        "validation": validation.as_dict(ndigits=ndigits),
                    },
                    "swarm": {
                        "drones": [
                            {
                                "type": "generic",
                                "settings": {
                                    "name": name,
                                    "trajectory": trajectories[name].as_dict(
                                        ndigits=ndigits
                                    ),
                                },
                            }
                            for name in natsorted(trajectories.keys())
                        ]
                    },
                    "meta": {},
                },
            },
            "output": {
                "format": "plot",
                "parameters": {
                    "plots": ",".join(plots),
                    "fps": fps,
                    "single_file": True,
                },
            },
        }

        with self._send_request("operations/render", data) as response:
            response.save_to_file(output)

    def get_limits(self) -> Limits:
        
        with self._send_request("queries/limits") as response:
            return Limits.from_json(response.as_json())

    def get_version(self) -> Version:
        
        with self._send_request("queries/version") as response:
            return Version.from_json(response.as_json())

    def match_points(
        self,
        source: Sequence[Coordinate3D],
        target: Sequence[Coordinate3D],
        *,
        radius: float | None = None,
    ) -> tuple[Mapping, float | None]:
        
        data = {"version": 1, "source": source, "target": target}
        if radius is not None:
            data["radius"] = radius

        with self._send_request("operations/match-points", data) as response:
            result = response.as_json()

        if result.get("version") != 1:
            raise SkybrushStudioAPIError("invalid response version")

        return result.get("mapping"), result.get("clearance")

    def plan_landing(
        self,
        points: Sequence[Coordinate3D],
        *,
        min_distance: float,
        velocity: float,
        target_altitude: float = 0,
        spindown_time: float = 5,
    ) -> tuple[list[int], list[int]]:
        
        data = {
            "version": 1,
            "points": points,
            "min_distance": float(min_distance),
            "velocity": float(velocity),
            "target_altitude": float(target_altitude),
            "spindown_time": float(spindown_time),
        }
        with self._send_request("operations/plan-landing", data) as response:
            result = response.as_json()

        if result.get("version") != 1:
            raise SkybrushStudioAPIError("invalid response version")

        return result["start_times"], result["durations"]

    def plan_smart_rth(
        self,
        source: Sequence[Coordinate3D],
        target: Sequence[Coordinate3D],
        *,
        max_velocity_xy: float,
        max_velocity_z: float,
        max_acceleration: float,
        min_distance: float,
        rth_model: str = "straight_line_with_neck",
    ) -> SmartRTHPlan:
        
        if not source or not target:
            return SmartRTHPlan.empty()

        data = {
            "version": 1,
            "source": source,
            "target": target,
            "max_velocity_xy": max_velocity_xy,
            "max_velocity_z": max_velocity_z,
            "max_acceleration": max_acceleration,
            "min_distance": min_distance,
            "rth_model": rth_model,
        }

        with self._send_request("operations/plan-smart-rth", data) as response:
            result = response.as_json()

        if result.get("version") != 1:
            raise SkybrushStudioAPIError("invalid response version")

        start_times = result.get("start_times")
        if start_times is None:
            raise SkybrushStudioAPIError(
                "invalid response format, start times are missing"
            )
        durations = result.get("durations")
        if durations is None:
            raise SkybrushStudioAPIError(
                "invalid response format, durations are missing"
            )
        inner_points = result.get("inner_points")
        if inner_points is None:
            raise SkybrushStudioAPIError(
                "invalid response format, inner points are missing"
            )

        return SmartRTHPlan(
            start_times=list(start_times),
            durations=list(durations),
            inner_points=list(inner_points),
        )

    def plan_transition(
        self,
        source: Sequence[Coordinate3D],
        target: Sequence[Coordinate3D],
        *,
        max_velocity_xy: float,
        max_velocity_z: float,
        max_acceleration: float,
        max_velocity_z_up: float | None = None,
        matching_method: str = "optimal",
    ) -> TransitionPlan:
        
        if not source or not target:
            return TransitionPlan.empty()

        data = {
            "version": 1,
            "source": source,
            "target": target,
            "max_velocity_xy": max_velocity_xy,
            "max_velocity_z": max_velocity_z,
            "max_acceleration": max_acceleration,
            "transition_method": "const_jerk",
            "matching_method": matching_method,
        }

        if max_velocity_z_up is not None:
            data["max_velocity_z_up"] = max_velocity_z_up

        with self._send_request("operations/plan-transition", data) as response:
            result = response.as_json()

        if result.get("version") != 1:
            raise SkybrushStudioAPIError("invalid response version")

        start_times = result.get("start_times")
        durations = result.get("durations")
        if start_times is None or durations is None:
            raise SkybrushStudioAPIError("invalid response format")

        mapping = result.get("mapping")
        clearance = result.get("clearance")

        return TransitionPlan(
            start_times=list(start_times),
            durations=list(durations),
            mapping=list(mapping) if mapping is not None else None,
            clearance=float(clearance) if clearance is not None else None,
        )
