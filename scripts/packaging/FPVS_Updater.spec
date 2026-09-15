# -*- mode: python ; coding: utf-8 -*-
"""Independent, one-file update and repair application; no Toolbox runtime bundle."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

repo_root = Path(SPECPATH).parents[1]
src_root = repo_root / "src"
app_icon = repo_root / "assets" / "ToolBox_Icon.ico"

# Do not collect all Main_App submodules or package data: that would bring the
# analysis tools and their scientific dependencies into the repair application.
forbidden_packages = (
    "Main_App.projects", "Main_App.processing", "Main_App.Performance", "Main_App.workers",
    "Tools", "config", "mne", "numpy", "scipy", "pandas", "matplotlib", "statsmodels",
    "pyvista", "vtk", "openpyxl", "PIL",
)
import sys
sys.path.insert(0, str(Path(SPECPATH)))
from updater_metadata import version_data
metadata, _version = version_data(repo_root)

a = Analysis(
    [str(src_root / "updater.py")],
    pathex=[str(src_root)],
    binaries=[],
    datas=[(str(metadata), ".")],
    hiddenimports=["Main_App.gui.updater_window"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(Path(SPECPATH) / "updater_qt_runtime.py")],
    excludes=list(forbidden_packages) + [
        "PyQt5",
        "PyQt6",
        "PySide2",
        "numpy",
        # components exposes unrelated main-application classes lazily;
        # updater surfaces use only its direct dialog/theme primitives.
        "Main_App.projects", "Main_App.gui.main_window", "Main_App.Shared.settings_manager",
    ],
    noarchive=False,
)

# The standard Qt hook eagerly imports QtCore to register an embedded qt.conf.
# Our PyPI PySide6 wheel configures itself on GUI import; worker/check processes
# need only the environment paths from the custom, GUI-neutral runtime hook.
a.scripts = [script for script in a.scripts if script[0] != "pyi_rth_pyside6"]

unexpected = sorted(
    name
    for name, _source, _kind in a.pure
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_packages)
)
if unexpected:
    raise RuntimeError("Updater collected Toolbox/runtime dependencies: " + ", ".join(unexpected))

# Match the main application's safeguard against unrelated ICU DLLs on host PATH.
a.binaries = [
    binary
    for binary in a.binaries
    if not (
        len(PureWindowsPath(binary[0]).parts) == 1
        and (
            PureWindowsPath(binary[0]).name.lower() == "icuuc.dll"
            or (
                PureWindowsPath(binary[0]).name.lower().startswith("icudt")
                and PureWindowsPath(binary[0]).name.lower().endswith(".dll")
            )
        )
    )
]
pyz = PYZ(a.pure)

# Onefile carries its own Python/Qt so it remains usable when Toolbox's _internal
# directory is damaged. A staged copy can replace the installed updater itself.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FPVS Toolbox Updater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_icon),
)
