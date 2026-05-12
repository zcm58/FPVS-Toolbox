from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from PySide6.QtWidgets import QApplication
except Exception:  # pragma: no cover - environment guard
    QApplication = None

if QApplication is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from Main_App.gui.main_window import (
    MainWindow,
    _should_show_no_excel_popup,
)
import Main_App.gui.main_window as main_window_module


@pytest.mark.parametrize(
    ("generated_paths", "create_excel", "expected_popup"),
    [(["dummy.xlsx"], False, False), ([], True, False), ([], False, True)],
)
def test_should_show_no_excel_popup_respects_generated_and_disk(
    tmp_path: Path,
    generated_paths: list[str],
    create_excel: bool,
    expected_popup: bool,
) -> None:
    output_root = tmp_path / "1 - Excel Data Files"
    output_root.mkdir()
    if create_excel:
        (output_root / "P01_results.xlsx").touch()

    assert _should_show_no_excel_popup(generated_paths, output_root) is expected_popup


def test_on_post_finished_marks_existing_excel_as_success(tmp_path: Path, qtbot) -> None:
    QApplication.instance() or QApplication([])

    win = MainWindow()
    qtbot.addWidget(win)

    output_root = tmp_path / "1 - Excel Data Files"
    output_root.mkdir()
    (output_root / "P01_results.xlsx").touch()

    win._last_job_success = False
    win._on_post_finished(
        {
            "file": "demo.bdf",
            "cancelled": False,
            "output_root": str(output_root),
            "generated_excel_paths": [],
            "existing_excel_paths": [str(output_root / "P01_results.xlsx")],
        }
    )

    assert win._last_job_success is True


def test_on_post_finished_preserves_earlier_run_success(tmp_path: Path, qtbot) -> None:
    QApplication.instance() or QApplication([])

    win = MainWindow()
    qtbot.addWidget(win)

    output_root = tmp_path / "1 - Excel Data Files"
    output_root.mkdir()

    win._run_had_successful_export = True
    win._last_job_success = True
    win._on_post_finished(
        {
            "file": "demo.bdf",
            "cancelled": False,
            "output_root": str(output_root),
            "generated_excel_paths": [],
            "existing_excel_paths": [],
        }
    )

    assert win._last_job_success is True


def test_export_with_post_process_keeps_prior_success_when_later_file_has_no_excel(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    QApplication.instance() or QApplication([])

    win = MainWindow()
    qtbot.addWidget(win)

    output_root = tmp_path / "1 - Excel Data Files"
    output_root.mkdir()
    win.save_folder_path = SimpleNamespace(
        get=lambda: str(output_root),
        set=lambda _value: None,
    )

    target_file = output_root / "P01_results.xlsx"

    def _fake_success(_app, _labels):
        target_file.write_text("ok", encoding="utf-8")

    monkeypatch.setattr(main_window_module, "_shared_post_process", _fake_success)
    win._export_with_post_process(["CondA"])
    assert win._last_job_success is True

    def _fake_no_output(app, _labels):
        app.log("Warning: Post-processing completed, but no Excel files were saved.")

    monkeypatch.setattr(main_window_module, "_shared_post_process", _fake_no_output)
    win._export_with_post_process(["CondB"])

    assert win._last_job_success is True


def test_refresh_run_excel_success_from_disk_detects_outputs_written_during_run(
    tmp_path: Path,
    qtbot,
) -> None:
    QApplication.instance() or QApplication([])

    win = MainWindow()
    qtbot.addWidget(win)

    output_root = tmp_path / "1 - Excel Data Files"
    output_root.mkdir()
    win._run_excel_output_root = str(output_root)
    win._run_excel_snapshot_before = {}

    (output_root / "P01_results.xlsx").write_text("ok", encoding="utf-8")
    win._refresh_run_excel_success_from_disk()

    assert win._last_job_success is True
