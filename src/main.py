#!/usr/bin/env python3
# ruff: noqa: E402
"""Entry point for launching the FPVS Toolbox GUI application (PySide6 only)."""

import os
import sys
from collections.abc import MutableMapping


def _configure_linux_qpa_platform(
    *,
    platform_name: str | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Use XCB on Wayland sessions before Qt or VTK is imported.

    PyVistaQt's VTK render window currently requires Qt's XCB platform on
    Linux/Wayland.  A native Wayland Qt window gives VTK an incompatible X11
    parent handle and can terminate during initial geometry setup with an
    X_ConfigureWindow ``BadWindow`` error.
    """
    platform_name = sys.platform if platform_name is None else platform_name
    environ = os.environ if environ is None else environ

    if not platform_name.startswith("linux") or environ.get("QT_QPA_PLATFORM"):
        return
    if (
        environ.get("XDG_SESSION_TYPE", "").strip().casefold() == "wayland"
        and environ.get("WAYLAND_DISPLAY", "").strip()
        and environ.get("DISPLAY", "").strip()
    ):
        environ["QT_QPA_PLATFORM"] = "xcb"


_configure_linux_qpa_platform()

from Main_App.workers.mp_env import set_blas_threads_single_process

set_blas_threads_single_process()

import multiprocessing as mp

from PySide6.QtCore import QCoreApplication

from config import FPVS_TOOLBOX_VERSION
from Main_App.gui.theme import apply_light_palette


def _configure_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return

    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


_configure_windows_dpi_awareness()

QCoreApplication.setOrganizationName("MississippiStateUniversity")
QCoreApplication.setOrganizationDomain("msstate.edu")
QCoreApplication.setApplicationName("FPVS Toolbox")
QCoreApplication.setApplicationVersion(FPVS_TOOLBOX_VERSION)

from Main_App import (  # noqa: E402
    configure_logging,
    get_settings,
    install_messagebox_logger,
)


def run_app() -> int:
    settings = get_settings()
    debug = settings.debug_enabled()
    configure_logging(debug)
    install_messagebox_logger(debug)

    from PySide6.QtWidgets import QApplication
    from Main_App.gui.main_window import MainWindow

    app = QApplication([])
    apply_light_palette(app)

    window = MainWindow()
    window.show()
    return app.exec()


def main() -> None:
    sys.exit(run_app())


if __name__ == "__main__":
    mp.freeze_support()
    if hasattr(sys, "frozen"):
        mp.set_executable(sys.executable)
    main()
