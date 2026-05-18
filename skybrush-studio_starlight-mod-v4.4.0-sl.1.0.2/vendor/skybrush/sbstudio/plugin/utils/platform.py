from pathlib import Path

import bpy

_tmpdir = None
"""Path object representing the temporary directory of the plugin within the
current Blender session."""


def get_temporary_directory() -> Path:
    
    global _tmpdir

    if _tmpdir is None:
        _tmpdir = Path(bpy.app.tempdir) / "skybrush"

    return _tmpdir


def open_file_with_default_application(path: str | Path) -> None:
    
    path = str(path)

    try:
        from os import startfile

        startfile(path)
    except ImportError:
        import platform
        from subprocess import call

        if platform.system() == "Darwin":
            
            call(["open", path])
        else:
            
            call(["xdg-open", path])
