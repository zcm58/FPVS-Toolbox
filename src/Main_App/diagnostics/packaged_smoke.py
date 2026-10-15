"""Bounded packaged-app diagnostics, with an explicitly opted-in visible probe.

The normal probe imports scientific dependencies without creating a Qt application.
Both modes use disposable settings/cache/project roots and never install updates.
"""

from __future__ import annotations

import argparse
import configparser
import faulthandler
import importlib
import json
import os
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


DEPENDENCY_IMPORTS = (
    "numpy", "scipy.signal", "scipy.stats", "pandas", "mne.io.edf.edf",
    "statsmodels.stats.multitest", "patsy", "openpyxl", "xlsxwriter",
    "nibabel", "pyvista", "PIL.Image", "requests",
)

TOOL_PAGE_FACTORIES = (
    ("Free Harmonic Clustering", "_ensure_free_harmonic_clustering_page"),
    ("SNR Plots", "_ensure_plot_generator_page"),
    ("Scalp Maps", "_ensure_publication_maps_page"),
    ("Standard FPVS Screening", "_ensure_stats_page"),
    ("Sensitivity Analysis", "_ensure_sensitivity_analysis_page"),
    ("LORETA Visualizer", "_ensure_loreta_visualizer_page"),
    ("Sequence Figure", "_ensure_sequence_figure_page"),
    ("Individual Detectability", "_ensure_individual_detectability_page"),
)


def show_tool_page(window: object, factory_name: str) -> object:
    """Use the real Main Window factories and reject an unavailable renderer."""
    page = getattr(window, factory_name)()
    window.stacked.setCurrentIndex(1)
    window.workspace_stack.setCurrentWidget(page)
    if factory_name == "_ensure_loreta_visualizer_page" and page.renderer is None:
        raise RuntimeError("Packaged LORETA 3D renderer could not initialize.")
    return page


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


def visible_probe(projects: Path, checkpoint: Callable[[str], None]) -> dict[str, object]:
    """Show the actual shell, process native events and exit after a short delay."""
    require_visible_opt_in()
    checkpoint("Import native GUI modules")
    from PySide6.QtCore import QCoreApplication, QThread, QTimer
    from PySide6.QtWidgets import QApplication

    from config import FPVS_TOOLBOX_VERSION
    from Main_App.gui import update_manager
    from Main_App.gui.theme import apply_light_palette
    from Main_App.projects import Project
    from Tools.Free_Harmonic_Clustering.gui import has_active_operations
    from Tools.LORETA_Visualizer.gui import LoretaVisualizerWindow

    # These are startup side effects, not part of the shell/rendering check.
    # Replace them only in this short-lived diagnostic process, before the
    # constructor takes its local references. Do not touch application settings.
    original_check = update_manager.check_for_updates_on_launch
    original_cleanup = update_manager.cleanup_old_executable
    original_template_load = LoretaVisualizerWindow._start_fsaverage_load
    update_manager.check_for_updates_on_launch = lambda _window: None
    update_manager.cleanup_old_executable = lambda: None
    # Exercise the real VTK/Qt renderer, but never fetch a large external MRI
    # template during bundle qualification. Scientific template use has its own
    # validation; this probe qualifies native tool construction and cleanup.
    LoretaVisualizerWindow._start_fsaverage_load = lambda _self, *, allow_fetch: None
    try:
        from Main_App.gui.main_window import MainWindow

        QCoreApplication.setOrganizationName("MississippiStateUniversity")
        QCoreApplication.setOrganizationDomain("msstate.edu")
        QCoreApplication.setApplicationName("FPVS Toolbox")
        QCoreApplication.setApplicationVersion(FPVS_TOOLBOX_VERSION)
        checkpoint("Create QApplication")
        app = QApplication([])
        apply_light_palette(app)
        checkpoint("Construct Main Window")
        window = MainWindow()
        if window.projectsRoot.resolve() != projects.resolve() or window.currentProject is not None:
            raise RuntimeError("Packaged smoke did not retain its isolated empty project root.")
        project_root = projects / "packaged-fixture"
        project_root.mkdir()
        project = Project(project_root, {"name": "Packaged acceptance fixture"})
        project.save()
        window.currentProject = project
        result: dict[str, object] = {"main_window_visible": False, "tool_pages": [],
                                    "external_template_fetch_skipped": True}
        pages = []
        next_page = 0
        shutdown_started: float | None = None

        def finish() -> None:
            nonlocal shutdown_started
            if shutdown_started is None:
                shutdown_started = time.monotonic()
                for page in pages:
                    shutdown = getattr(page, "shutdown", None)
                    if callable(shutdown):
                        checkpoint(f"Stop tool workers: {type(page).__name__}")
                        shutdown()
            if has_active_operations() or any(thread.isRunning() for thread in window.findChildren(QThread)):
                if time.monotonic() - shutdown_started < 15:
                    QTimer.singleShot(100, finish)
                    return
                result["error"] = "Packaged tool background work did not stop within 15 seconds."
                app.exit(1)
                return
            for page in pages:
                checkpoint(f"Close tool: {type(page).__name__}")
                if not page.close():
                    result["error"] = "Packaged tool refused to close after worker cleanup."
                    app.exit(1)
                    return
            result["main_window_visible"] = window.isVisible()
            result["window_title"] = window.windowTitle()
            result["application_version"] = app.applicationVersion()
            window.currentProject = None
            checkpoint("Close Main Window")
            result["main_window_closed"] = window.close()
            app.quit()

        def advance() -> None:
            nonlocal next_page
            try:
                if pages and not pages[-1].isVisible():
                    raise RuntimeError(f"Packaged tool page is not visible: {TOOL_PAGE_FACTORIES[next_page - 1][0]}")
                if next_page == len(TOOL_PAGE_FACTORIES):
                    finish()
                    return
                label, factory = TOOL_PAGE_FACTORIES[next_page]
                checkpoint(f"Construct and show tool: {label}")
                pages.append(show_tool_page(window, factory))
                result["tool_pages"].append(label)
                checkpoint(f"Process native events: {label}")
                next_page += 1
                QTimer.singleShot(250, advance)
            except Exception as error:
                label = TOOL_PAGE_FACTORIES[min(next_page, len(TOOL_PAGE_FACTORIES) - 1)][0]
                result["error"] = f"{label}: {type(error).__name__}: {error}"
                finish()

        checkpoint("Show Main Window")
        window.show()
        QTimer.singleShot(500, advance)
        checkpoint("Run native event loop")
        exit_code = app.exec()
        checkpoint("Native event loop stopped")
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        if exit_code != 0 or not result["main_window_visible"] or not result.get("main_window_closed"):
            raise RuntimeError("Packaged Main Window did not complete its visible smoke.")
        if result["application_version"] != FPVS_TOOLBOX_VERSION:
            raise RuntimeError("Packaged application version differs from config.py.")
        return result
    finally:
        update_manager.check_for_updates_on_launch = original_check
        update_manager.cleanup_old_executable = original_cleanup
        LoretaVisualizerWindow._start_fsaverage_load = original_template_load


@contextmanager
def native_crash_trace(report_path: Path) -> Iterator[None]:
    """Retain a Python stack when a frozen window hits a fatal native exception."""
    with report_path.with_suffix(".fault.log").open("w", encoding="utf-8") as stream:
        already_enabled = faulthandler.is_enabled()
        if not already_enabled:
            faulthandler.enable(file=stream, all_threads=True)
        try:
            yield
        finally:
            if not already_enabled:
                faulthandler.disable()


def run_check(report_path: Path, *, visible: bool = False, workflows: bool = False) -> int:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "schema_version": 1,
        "mode": "visible" if visible else "workflows" if workflows else "dependencies",
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": str(Path(sys.executable).resolve()),
        "passed": False,
        "gui_exercised": False,
        "network": False,
        "installer": False,
    }

    def checkpoint(stage: str) -> None:
        report["stage"] = stage
        report.setdefault("checkpoints", []).append(stage)
        # Close after each write so fatal native crashes still leave the most
        # recent operation and a failed result in the retained CI evidence.
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    checkpoint("Start packaged diagnostics")
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
                with native_crash_trace(report_path):
                    report.update(visible_probe(projects, checkpoint))
                report["gui_exercised"] = True
            if workflows:
                from Main_App.diagnostics.packaged_workflows import run_workflows

                report["workflows"] = run_workflows(report_path.with_suffix(".artifacts"))
            report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    report["qt_widgets_loaded"] = "PySide6.QtWidgets" in sys.modules
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--packaging-check", type=Path)
    mode.add_argument("--packaged-smoke-output", type=Path)
    mode.add_argument("--packaged-workflow-output", type=Path)
    parsed = parser.parse_args(arguments)
    return run_check(
        parsed.packaged_smoke_output or parsed.packaged_workflow_output or parsed.packaging_check,
        visible=parsed.packaged_smoke_output is not None,
        workflows=parsed.packaged_workflow_output is not None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
