"""Toolbox identity adapter; independent of config's scientific imports.

Source config.py remains the sole version owner. Packaging freezes that value
as helper data, so repair still works if the main application is damaged.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

RELEASE_REPOSITORY = "zcm58/FPVS-Toolbox-Repo"
APP_NAME = "FPVS Toolbox"
APPLICATION_FILENAME = "FPVS_Toolbox.exe"
UPDATER_FILENAME = "FPVS Toolbox Updater.exe"
UNINSTALL_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{77E578C2-2B30-4015-AE3F-9CE6191423F4}_is1"
)


def source_version(config_path: Path) -> str:
    module = ast.parse(config_path.read_text(encoding="utf-8-sig"))
    for node in module.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "FPVS_TOOLBOX_VERSION":
                value = ast.literal_eval(node.value)
                if isinstance(value, str):
                    return value
    raise RuntimeError("Toolbox source version is missing.")


def _version() -> str:
    if getattr(sys, "frozen", False):
        metadata = Path(getattr(sys, "_MEIPASS")) / "toolbox-updater-version.json"
        version = json.loads(metadata.read_text(encoding="utf-8"))["version"]
        if not isinstance(version, str):
            raise RuntimeError("Invalid Toolbox updater version metadata.")
        return version
    return source_version(Path(__file__).resolve().parents[2] / "config.py")


APP_VERSION = _version()
