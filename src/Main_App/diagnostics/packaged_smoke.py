"""Bounded packaged-app diagnostics, with an explicitly opted-in visible probe.

The normal probe imports scientific dependencies without creating a Qt application.
Both modes use disposable settings/cache/project roots and never install updates.
"""

from __future__ import annotations

import argparse
import configparser
import importlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEPENDENCY_IMPORTS = (
    "numpy", "scipy.signal", "scipy.stats", "pandas", "mne.io.edf.edf",
    "statsmodels.stats.multitest", "patsy", "openpyxl", "xlsxwriter",
    "nibabel", "pyvista", "PIL.Image", "requests",
)


@contextmanager
def isolated_environment() -> Iterator[Path]:
    """Keep diagnostics away from real preferences, legacy migration and projects."""
    with tempfile.TemporaryDirectory(prefix="fpvs-packaged-smoke-") as directory:
        root = Path(directory)
        projects = root / "projects"
        projects.mkdir()
        settings = root / "config" / "settings"
        settings.mkdir(parents=True)
        ini = configparser.ConfigParser()
        ini.read_dict({
            "paths": {"projectsRoot": str(projects)},
            "recent": {"projects": "[]"},
            # Seed every legacy Qt migration key so no user registry/settings read
            # can silently import a real projects root or recent project list.
            "updates": {"last_checked_utc": "2000-01-01T00:00:00+00:00"},
        })
        with (settings / "settings.ini").open("w", encoding="utf-8") as stream:
            ini.write(stream)
        overrides = {
            "FPVS_CONFIG_HOME": str(root / "config"),
            "MPLCONFIGDIR": str(root / "matplotlib"),
            "MPLBACKEND": "Agg",
            "MNE_DONTWRITE_HOME": "true",
            "_MNE_FAKE_HOME_DIR": str(root / "mne"),
        }
        previous = {key: os.environ.get(key) for key in overrides}
        os.environ.update(overrides)
        try:
            yield projects
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def dependency_report() -> dict[str, str]:
    """Exercise lazy DLL/import paths without creating windows or reading EEG."""
    imported = {}
    for name in DEPENDENCY_IMPORTS:
        module = importlib.import_module(name)
        imported[name] = str(getattr(module, "__version__", "imported"))
    return imported


def require_visible_opt_in() -> None:
    if os.environ.get("FPVS_ALLOW_QT_TESTS") != "1":
        raise RuntimeError("Visible packaged smoke requires FPVS_ALLOW_QT_TESTS=1.")
    platform = os.environ.get("QT_QPA_PLATFORM", "").split(":", 1)[0].casefold()
    if platform in {"offscreen", "minimal"}:
        raise RuntimeError("Visible packaged smoke requires the native Qt platform.")


def visible_probe(projects: Path) -> dict[str, object]:
    """Show the actual shell, process native events and exit after a short delay."""
    require_visible_opt_in()
    from PySide6.QtCore import QCoreApplication, QTimer
    from PySide6.QtWidgets import QApplication

    from config import FPVS_TOOLBOX_VERSION
    from Main_App.gui import update_manager
    from Main_App.gui.theme import apply_light_palette

    # These are startup side effects, not part of the shell/rendering check.
    # Replace them only in this short-lived diagnostic process, before the
    # constructor takes its local references. Do not touch application settings.
    original_check = update_manager.check_for_updates_on_launch
    original_cleanup = update_manager.cleanup_old_executable
    update_manager.check_for_updates_on_launch = lambda _window: None
    update_manager.cleanup_old_executable = lambda: None
    try:
        from Main_App.gui.main_window import MainWindow

        QCoreApplication.setOrganizationName("MississippiStateUniversity")
        QCoreApplication.setOrganizationDomain("msstate.edu")
        QCoreApplication.setApplicationName("FPVS Toolbox")
        QCoreApplication.setApplicationVersion(FPVS_TOOLBOX_VERSION)
        app = QApplication([])
        apply_light_palette(app)
        window = MainWindow()
        if window.projectsRoot.resolve() != projects.resolve() or window.currentProject is not None:
            raise RuntimeError("Packaged smoke did not retain its isolated empty project root.")
        result: dict[str, object] = {"main_window_visible": False}

        def finish() -> None:
            result["main_window_visible"] = window.isVisible()
            result["window_title"] = window.windowTitle()
            result["application_version"] = app.applicationVersion()
            result["main_window_closed"] = window.close()
            app.quit()

        window.show()
        QTimer.singleShot(1500, finish)
        exit_code = app.exec()
        if exit_code != 0 or not result["main_window_visible"] or not result.get("main_window_closed"):
            raise RuntimeError("Packaged Main Window did not complete its visible smoke.")
        if result["application_version"] != FPVS_TOOLBOX_VERSION:
            raise RuntimeError("Packaged application version differs from config.py.")
        return result
    finally:
        update_manager.check_for_updates_on_launch = original_check
        update_manager.cleanup_old_executable = original_cleanup


def run_check(report_path: Path, *, visible: bool = False) -> int:
    report: dict[str, object] = {
        "schema_version": 1,
        "mode": "visible" if visible else "dependencies",
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": str(Path(sys.executable).resolve()),
        "passed": False,
        "gui_exercised": False,
        "network": False,
        "installer": False,
    }
    try:
        if visible:
            require_visible_opt_in()
        with isolated_environment() as projects:
            from Main_App.updates.application import APP_VERSION

            report["metadata_version"] = APP_VERSION
            report["dependencies"] = dependency_report()
            from config import FPVS_TOOLBOX_VERSION

            report["version"] = FPVS_TOOLBOX_VERSION
            if FPVS_TOOLBOX_VERSION != APP_VERSION:
                raise RuntimeError("Main bundle config version differs from embedded updater metadata.")
            if "PySide6.QtWidgets" in sys.modules:
                raise RuntimeError("Dependency-only smoke unexpectedly imported QtWidgets.")
            if visible:
                report.update(visible_probe(projects))
                report["gui_exercised"] = True
            report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["qt_widgets_loaded"] = "PySide6.QtWidgets" in sys.modules
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--packaging-check", type=Path)
    mode.add_argument("--packaged-smoke-output", type=Path)
    parsed = parser.parse_args(arguments)
    return run_check(
        parsed.packaged_smoke_output or parsed.packaging_check,
        visible=parsed.packaged_smoke_output is not None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
