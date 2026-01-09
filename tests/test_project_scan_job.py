import importlib.util
from pathlib import Path

import pytest


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


if not _module_available("PySide6"):
    pytest.skip("PySide6 not available", allow_module_level=True)

from PySide6.QtCore import QCoreApplication  # noqa: E402

from Main_App.PySide6_App.Backend import project_manager  # noqa: E402


def _write_project(root: Path, name: str) -> None:
    project_root = root / name
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "project.json").write_text("{}", encoding="utf-8")


def test_project_scan_job_emits_finished(tmp_path: Path) -> None:
    QCoreApplication.instance() or QCoreApplication([])
    _write_project(tmp_path, "Project 1")
    _write_project(tmp_path, "Project 2")

    job = project_manager._ProjectScanJob(tmp_path)
    finished_payload: list[list] = []
    errors: list[str] = []

    job.signals.finished.connect(lambda payload: finished_payload.append(payload))
    job.signals.error.connect(lambda message: errors.append(message))

    job.run()

    assert not errors
    assert finished_payload
    assert len(finished_payload[0]) == 2


def test_project_scan_job_emits_cancel_error(tmp_path: Path) -> None:
    QCoreApplication.instance() or QCoreApplication([])
    _write_project(tmp_path, "Project 1")

    job = project_manager._ProjectScanJob(tmp_path)
    errors: list[str] = []

    job.signals.error.connect(lambda message: errors.append(message))

    job.request_cancel()
    job.run()

    assert errors == [project_manager.CANCEL_SCAN_MESSAGE]
