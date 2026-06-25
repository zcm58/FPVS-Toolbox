"""Cross-platform helpers for opening local files and folders from PySide6 UIs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_path_in_file_manager(path: str | Path) -> bool:
    """Open a local path with the platform file manager."""
    path_text = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path_text)  # noqa: S606
        return True
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path_text))
