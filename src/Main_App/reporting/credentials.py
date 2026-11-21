"""Native OS credential storage; no project/file/plaintext fallback."""

from __future__ import annotations

import ctypes
import hashlib
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class CredentialStore:
    """Separate path/protocol/study scoped access, matching Studio's OS policy."""

    def __init__(self, project_root: Path, scope: dict[str, str]):
        identity = hashlib.sha256(
            f"https://openfpvs.com\n{Path(project_root).resolve()}\n{scope['protocol_sha256']}\n{scope['study_id']}".encode()
        ).hexdigest()
        self.target = f"FPVS-Toolbox/Analysis-Reporting/{identity}"

    @staticmethod
    def _windows_api():
        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        ]
        api.CredReadW.restype = wintypes.BOOL
        api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api

    def _linux(self, operation: str, token: str | None = None) -> str:
        command = ["secret-tool", operation]
        if operation == "store":
            command += ["--label=FPVS Toolbox analysis reporting"]
        command += ["application", "fpvs-toolbox-analysis", "scope", self.target]
        try:
            result = subprocess.run(command, input=token, text=True, capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError("Reporting requires an unlocked Linux Secret Service and secret-tool.") from None
        if result.returncode != 0:
            if operation == "lookup" and not result.stderr.strip():
                return ""
            raise RuntimeError("The OS credential manager could not access reporting credentials.")
        return result.stdout.strip()

    def load(self) -> str | None:
        if sys.platform == "win32":
            api = self._windows_api()
            pointer = ctypes.POINTER(_Credential)()
            if not api.CredReadW(self.target, 1, 0, ctypes.byref(pointer)):
                if ctypes.get_last_error() == 1168:
                    return None
                raise RuntimeError("The OS credential manager could not read reporting access.")
            try:
                if pointer.contents.CredentialBlobSize > 512:
                    raise ValueError("Stored reporting credential is invalid.")
                token = ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize).decode(
                    "utf-8"
                )
            finally:
                api.CredFree(pointer)
        elif sys.platform.startswith("linux"):
            token = self._linux("lookup")
        else:
            raise RuntimeError("Reporting requires Windows Credential Manager or Linux Secret Service.")
        if not token:
            return None
        self._validate(token)
        return token

    @staticmethod
    def _validate(token: str) -> None:
        if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("Reporting credential is invalid.")

    def save(self, token: str) -> None:
        self._validate(token)
        if sys.platform == "win32":
            raw = token.encode("utf-8")
            blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
            value = _Credential()
            value.Type, value.TargetName, value.Persist = 1, self.target, 2
            value.CredentialBlobSize = len(raw)
            value.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
            value.UserName = "FPVS Toolbox analysis reporting"
            if not self._windows_api().CredWriteW(ctypes.byref(value), 0):
                raise RuntimeError("The OS credential manager could not save reporting access.")
        elif sys.platform.startswith("linux"):
            self._linux("store", token)
        else:
            raise RuntimeError("Reporting requires Windows Credential Manager or Linux Secret Service.")
