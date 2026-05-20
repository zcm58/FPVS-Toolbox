"""Installer launch helper for the FPVS Toolbox updater."""

from __future__ import annotations

import subprocess
from pathlib import Path

from Main_App.updates.models import UpdateError


def launch_installer(
    installer_path: Path,
    *,
    relaunch_after_install: bool = True,
) -> subprocess.Popen[bytes]:
    """Launch a downloaded installer after the GUI has obtained user confirmation."""

    path = Path(installer_path)
    if not path.is_file():
        raise UpdateError(f"Installer file does not exist: {path}")
    if path.suffix.lower() != ".exe":
        raise UpdateError("The update installer must be a Windows .exe file.")
    command = [str(path)]
    if relaunch_after_install:
        command.append("/RELAUNCH=1")
    return subprocess.Popen(command, close_fds=True)
