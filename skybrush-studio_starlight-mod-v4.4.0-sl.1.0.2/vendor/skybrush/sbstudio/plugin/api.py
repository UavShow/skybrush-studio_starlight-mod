import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from socket import gaierror
from typing import TypeVar
from urllib.error import URLError

from sbstudio.api import SkybrushStudioAPI
from sbstudio.api.errors import NoOnlineAccessAllowedError
from sbstudio.api.version import ensure_backend_version
from sbstudio.errors import SkybrushStudioError
from sbstudio.plugin.errors import SkybrushStudioExportWarning

__all__ = ("get_api",)

_fallback_api_key: str = "trial"
"""Fallback API key to use when the user did not enter any API key"""

T = TypeVar("T")




log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_api_from_url_and_key_or_license(url: str, key: str, license_file: str):
    
    global _fallback_api_key

    try:
        result = SkybrushStudioAPI(
            api_key=key or (None if license_file else _fallback_api_key),
            license_file=license_file or None,
        )
        if url:
            result.url = url
    except ValueError as ex:
        log.error(f"Could not initialize Skybrush Studio API: {str(ex)}")
        raise
    except Exception as ex:
        log.error(f"Unhandled exception in Skybrush Studio API initialization: {ex!r}")
        raise

    
    
    
    
    result._skip_ssl_checks()

    return result


def get_api(*, check_version: bool = True) -> SkybrushStudioAPI:
    
    from sbstudio.plugin.model.global_settings import get_preferences
    from sbstudio.plugin.plugin_helpers import is_online_access_allowed

    if not is_online_access_allowed():
        raise NoOnlineAccessAllowedError()

    api_key: str
    server_url: str
    license_file: str

    prefs = get_preferences()
    api_key = str(prefs.api_key).strip()
    license_file = str(prefs.license_file).strip()
    server_url = str(prefs.server_url).strip()

    api = _get_api_from_url_and_key_or_license(server_url, api_key, license_file)

    if check_version:
        ensure_backend_version(api)

    return api


@contextmanager
def call_api_from_blender_operator(
    operator, what: str = "operation", *, check_version: bool = True
) -> Iterator[SkybrushStudioAPI]:
    
    default_message = f"Error while invoking {what} on the Skybrush Studio server"
    try:
        
        
        
        
        yield get_api(check_version=check_version)
    except SkybrushStudioExportWarning as ex:
        operator.report({"WARNING"}, str(ex))
        raise
    except SkybrushStudioError as ex:
        operator.report({"ERROR"}, ex.format_message() or default_message)
        raise
    except URLError as ex:
        if isinstance(ex.reason, ConnectionRefusedError):
            message = f"{default_message}: Connection refused. Is the server running?"
        elif isinstance(ex.reason, gaierror):
            message = f"{default_message}: Could not resolve server URL. Are you connected to the Internet?"
        elif isinstance(ex.reason, OSError):
            message = f"{default_message}: {ex.reason.strerror}"
        elif isinstance(ex.reason, str):
            message = f"{default_message}: {ex.reason}"
        else:
            message = default_message
        operator.report({"ERROR"}, message)
    except ConnectionRefusedError:
        operator.report(
            {"ERROR"}, f"{default_message}: Connection refused. Is the server running?"
        )
        raise
    except gaierror:
        
        
        
        operator.report(
            f"{default_message}: Could not resolve server URL. Are you connected to the Internet?"
        )
    except OSError as ex:
        operator.report({"ERROR"}, f"{default_message}: {ex.strerror}")
        raise
    except Exception:
        operator.report({"ERROR"}, default_message)
        raise


def set_fallback_api_key(value: str | None) -> None:
    
    global _fallback_api_key
    _fallback_api_key = str(value) if value is not None else ""
