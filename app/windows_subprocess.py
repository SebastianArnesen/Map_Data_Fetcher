"""Hide console windows for child processes on Windows."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_PATCHED = False


def gui_executable() -> str:
    """Prefer pythonw.exe for GUI restarts when running from a CPython install."""
    exe = Path(sys.executable)
    if os.name == "nt" and exe.name.lower() == "python.exe":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.is_file():
            return str(pythonw)
    return str(exe)


def hidden_popen_kwargs() -> dict:
    """Keyword arguments for subprocess.Popen that suppress console windows on Windows."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags |= subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS
    return {"startupinfo": startupinfo, "creationflags": creationflags}


def install_windows_subprocess_patch() -> None:
    """Ensure all subprocess.Popen calls on Windows launch without a console."""
    global _PATCHED
    if _PATCHED or os.name != "nt":
        return
    _PATCHED = True
    original_popen = subprocess.Popen

    def popen_no_console(*args, **kwargs):
        extra = hidden_popen_kwargs()
        if "startupinfo" not in kwargs:
            kwargs["startupinfo"] = extra["startupinfo"]
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | int(extra["creationflags"])
        return original_popen(*args, **kwargs)

    subprocess.Popen = popen_no_console  # type: ignore[assignment]
