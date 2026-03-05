from pathlib import Path

import pytest

try:
    from PySide6.QtWidgets import QApplication
except Exception:  # pragma: no cover - environment guard
    QApplication = None

if QApplication is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from Main_App.PySide6_App.GUI.main_window import (
    MainWindow,
    _should_show_no_excel_popup,
)


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
