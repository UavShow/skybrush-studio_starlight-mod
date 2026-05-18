

from datetime import datetime
from email.utils import parsedate_to_datetime
from errno import ECONNREFUSED, ENETUNREACH
from json import load
from socket import (
    AF_INET,
    IPPROTO_UDP,
    SOCK_DGRAM,
    socket,
)
from socket import (
    timeout as SocketTimeoutError,
)
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

__all__ = ("SkybrushViewerBridge",)


class SkybrushViewerError(RuntimeError):
    pass


class SkybrushViewerNotFoundError(SkybrushViewerError):
    

    pass


class SkybrushViewerBridge:
    

    def __init__(self):
        
        self._discovery = SSDPAppDiscovery("urn:collmot-com:service:skyc-validator:1")

    def _send_request(self, path: str, *args, **kwds) -> dict:
        
        force = False

        while True:
            url = self._discovery.discover(force=force)
            if url is None:
                raise SkybrushViewerNotFoundError()

            if url.endswith("/"):
                url = url[:-1]
            if path.startswith("/"):
                path = path[1:]
            url_and_path = f"{url}/api/v1/{path}"

            request = Request(url_and_path, *args, **kwds)

            try:
                with urlopen(request) as response:
                    result = load(response)
                    if isinstance(result, dict):
                        return result
                    else:
                        raise SkybrushViewerError(
                            "Invalid response received from Skybrush Viewer"
                        )

            except HTTPError as err:
                
                
                self._discovery.invalidate()
                if err.code >= 500:
                    raise SkybrushViewerError(
                        "Skybrush Viewer indicated an unexpected error"
                    ) from None
                elif err.code == 404:
                    
                    self._discovery.invalidate()
                    raise SkybrushViewerNotFoundError() from None
                elif err.code == 400:
                    
                    raise SkybrushViewerError(
                        "Skybrush Viewer indicated that the input format is invalid"
                    ) from None
                else:
                    raise

            except URLError as err:
                if err.reason and getattr(err.reason, "errno", None) == ECONNREFUSED:
                    
                    pass
                else:
                    
                    
                    self._discovery.invalidate()
                    raise

            except Exception:
                
                
                self._discovery.invalidate()
                raise

            if force:
                raise SkybrushViewerNotFoundError()
            else:
                
                force = True

    def check_running(self) -> bool:
        
        result = self._send_request("ping")
        return bool(result.get("result"))

    def load_show_for_validation(
        self, show_data: bytes, *, filename: str | None = None
    ) -> None:
        
        headers = {"Content-Type": "application/skybrush-compiled"}
        if filename:
            headers["X-Skybrush-Viewer-Title"] = filename[:512]

        result = self._send_request(
            "load",
            data=show_data,
            headers=headers,
        )

        if not result.get("result"):
            raise SkybrushViewerError("Invalid response received from Skybrush Viewer")


class SSDPAppDiscovery:
    

    def __init__(self, urn: str, *, max_age: float = 600):
        
        self._sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        self._sock.settimeout(1)

        self._urn = urn
        self._max_age = float(max_age)
        self._last_checked_at = 0
        self._url = None  

    def discover(self, force: bool = False) -> str | None:
        
        if force:
            self.invalidate()
        self._update_url_if_needed()
        return self._url

    def invalidate(self) -> None:
        
        self._last_checked_at = 0
        self._url = None

    def _update_url_if_needed(self) -> None:
        
        now = monotonic()
        if self._url is None or now - self._last_checked_at > self._max_age:
            self._url = self._update_url()
            self._last_checked_at = monotonic()

    def _update_url(self) -> str | None:
        
        message = (
            f"M-SEARCH * HTTP/1.1\r\n"
            f"HOST:239.255.255.250:1900\r\n"
            f"ST:{self._urn}\r\n"
            f"MX:2\r\n"
            f'MAN:"ssdp:discover"\r\n'
            f"\r\n"
        ).encode("ascii")

        
        
        try:
            self._sock.sendto(message, ("239.255.255.250", 1900))
        except OSError as ex:
            if ex.errno == ENETUNREACH:
                
                
                self._sock.sendto(message, ("127.0.0.1", 1900))

        
        
        attempts = 10
        location = None
        while attempts > 0:
            attempts -= 1
            date_ok = False
            location = None

            try:
                
                
                
                
                data, addr = self._sock.recvfrom(65507)
            except SocketTimeoutError:
                return

            if not data.startswith(b"HTTP/1.1 200 OK\r\n"):
                continue

            lines = data.split(b"\r\n")
            for line in lines:
                key, _, value = line.partition(b":")
                key = key.decode("ascii", "replace").upper().strip()
                if key == "LOCATION":
                    location = value.decode("ascii", "replace").strip()
                elif key == "DATE":
                    try:
                        parsed_date = parsedate_to_datetime(
                            value.decode("ascii", "replace")
                        )
                    except ValueError:
                        continue

                    if (
                        parsed_date.tzinfo is None
                        or parsed_date.tzinfo.utcoffset(parsed_date) is None
                    ):
                        diff = parsed_date - datetime.now()
                    else:
                        diff = parsed_date - datetime.now(parsed_date.tzinfo)

                    if abs(diff.total_seconds()) < 5:
                        date_ok = True

            if location and date_ok:
                break

        return location
