"""Windows UAC adapter for Toolbox's existing all-users installation option."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from Main_App.updates.models import UpdateError
from Main_App.updates.process_launch import independent_dll_search


def launch_elevated_installer(command: list[str]):
    """Request UAC only for a verified, explicitly selected all-users update."""
    if sys.platform != "win32":
        raise UpdateError("All-users installation requires Windows.")
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = command[0]
    info.lpParameters = subprocess.list2cmdline(command[1:])
    info.lpDirectory = str(Path(command[0]).parent)
    info.nShow = 1
    with independent_dll_search():
        if not shell.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
            raise UpdateError("Administrator approval was canceled or Windows could not start setup.")

    class ElevatedSetup:
        def wait(self) -> int:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.GetExitCodeProcess.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            try:
                if kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF) != 0:
                    raise UpdateError("Could not wait for the administrator installer.")
                code = wintypes.DWORD()
                if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
                    raise UpdateError("Could not read the administrator installer result.")
                return code.value
            finally:
                kernel.CloseHandle(info.hProcess)

    return ElevatedSetup()
