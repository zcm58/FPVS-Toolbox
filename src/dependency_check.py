"""Dependency checking utilities for FPVS Toolbox."""

from __future__ import annotations

from importlib import import_module
from typing import Iterable

# List of required packages and the module names to import
REQUIRED_PACKAGES: Iterable[tuple[str, str]] = [
    ("mne", "mne"),
    ("numpy", "numpy"),
    ("pandas", "pandas"),
    ("scipy", "scipy"),
    ("customtkinter", "customtkinter"),
    ("statsmodels", "statsmodels"),
    ("nibabel", "nibabel"),
    ("pyvista", "pyvista"),
    ("pyvistaqt", "pyvistaqt"),
]


def missing_dependencies() -> list[str]:
    """Return a list of packages that are not installed."""
    missing: list[str] = []
    for pkg_name, module_name in REQUIRED_PACKAGES:
        try:
            import_module(module_name)
        except Exception:
            missing.append(pkg_name)
    return missing


def check_dependencies(show_message: bool = True) -> bool:
    """Check for required packages and optionally show a message box."""
    missing = missing_dependencies()
    if not missing:
        return True

    msg = (
        "The following Python packages are required but not installed:\n"
        f"{', '.join(missing)}\n"
        "Please install them before running the FPVS Toolbox."
    )

    if show_message:
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Missing Dependencies", msg)
            root.destroy()
        except Exception:
            print(msg)
    else:
        print(msg)

    return False
