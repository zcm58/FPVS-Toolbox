"""Launch independent processes without inheriting the frozen helper's runtime.

PyInstaller's public reset flag gives a same-executable child its own extraction
lifetime. Windows DLL search and runtime-hook paths must also be reset for native
setup and for a restarted Toolbox with a different bundle.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from Main_App.updates.models import UpdateError

_LOG = logging.getLogger(__name__)
_DLL_SEARCH_LOCK = RLock()
_RUNTIME_PATH_VARIABLES = (
    "PATH",
    "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    "QML2_IMPORT_PATH",
    "QML_IMPORT_PATH",
)


def independent_process_environment() -> dict[str, str]:
    """Return a child-only environment; never edit bootloader-private variables."""
    environment = dict(os.environ)
    # Required even when launching the same staged onefile helper again: it may
    # outlive this process and cannot reuse this process's temporary extraction.
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    extraction = getattr(sys, "_MEIPASS", None)
    if not getattr(sys, "frozen", False) or not isinstance(extraction, str):
        return environment
    bundle_root = Path(os.path.normpath(extraction))
    for name in _RUNTIME_PATH_VARIABLES:
        value = environment.get(name)
        if value is None:
            continue
        kept = []
        for entry in value.split(os.pathsep):
            path = Path(os.path.normpath(entry.strip('"')))
            if path.is_absolute() and (path == bundle_root or bundle_root in path.parents):
                continue
            kept.append(entry)
        if kept:
            environment[name] = os.pathsep.join(kept)
        else:
            environment.pop(name, None)
    return environment


def _windows_dll_api() -> Any:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDllDirectoryW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
    kernel.GetDllDirectoryW.restype = wintypes.DWORD
    kernel.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
    kernel.SetDllDirectoryW.restype = wintypes.BOOL
    return kernel


@contextmanager
def independent_dll_search() -> Iterator[None]:
    """Clear the frozen Windows DLL directory only for the process-creation call.

    The setting is process-wide, so cooperating updater launches are serialized.
    Restoration runs on success and failure. A restoration error is logged rather
    than replacing a launch error or losing a successfully created setup process.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        yield
        return
    import ctypes

    with _DLL_SEARCH_LOCK:
        kernel = _windows_dll_api()
        buffer = ctypes.create_unicode_buffer(32768)
        ctypes.set_last_error(0)
        length = kernel.GetDllDirectoryW(len(buffer), buffer)
        if length >= len(buffer) or (length == 0 and ctypes.get_last_error() != 0):
            raise UpdateError("Could not preserve the updater's Windows DLL search path.")
        previous = buffer.value if length else None
        if not kernel.SetDllDirectoryW(None):
            raise UpdateError("Could not prepare the Windows DLL search path for the update.")
        try:
            yield
        finally:
            if not kernel.SetDllDirectoryW(previous):
                _LOG.error("updater_dll_search_restore_failed", extra={"error": ctypes.get_last_error()})


def launch_independent_process(command: list[str], **options: Any) -> subprocess.Popen[bytes]:
    """Spawn one independent helper, native installer, or restarted Toolbox."""
    if "env" in options:
        raise ValueError("Independent updater launches own their child environment.")
    environment = independent_process_environment()
    with independent_dll_search():
        return subprocess.Popen(command, env=environment, **options)
