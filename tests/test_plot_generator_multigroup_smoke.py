from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox
    from Main_App.PySide6_App.Backend.project import EXCEL_SUBFOLDER_NAME
    from Tools.Plot_Generator import gui as plot_gui
    from Tools.Plot_Generator import worker as plot_worker
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pytest.skip("PySide6 is required for Plot Generator smoke tests", allow_module_level=True)


@pytest.fixture
def plot_smoke_env(monkeypatch):
    """Patch heavy plot generator helpers for lightweight smoke tests."""

    monkeypatch.setattr(plot_gui, "load_rois_from_settings", lambda: {"ROI": ["Cz"]}, raising=False)

    data_store: dict[str, object] = {
        "freqs": [1.0, 2.0],
        "subjects": {},
    }

    def fake_collect(self, condition: str, *, offset: int = 0, total_override: int | None = None):  # noqa: ARG001
        subject_data = data_store["subjects"].get(condition, {})
        subject_map = subject_data if isinstance(subject_data, dict) else {}
        self._unknown_subject_files.clear()
        if self.enable_group_overlay and self.multi_group_mode and self.subject_groups:
            for pid in subject_map.keys():
                if pid not in self.subject_groups:
                    self._unknown_subject_files.add(f"{pid}.xlsx")
        if not subject_map:
            return [], {}
        return list(data_store["freqs"]), subject_map

    monkeypatch.setattr(plot_worker._Worker, "_collect_data", fake_collect, raising=False)

    plot_records: list[dict] = []

    def fake_plot(self, freqs, roi_data, group_curves=None):  # noqa: ANN001
        plot_records.append({
            "freqs": list(freqs),
            "roi_data": roi_data,
            "group_curves": group_curves or {},
        })

    monkeypatch.setattr(plot_worker._Worker, "_plot", fake_plot, raising=False)

    def fake_finish(self):
        self.gen_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._conditions_queue.clear()
        self._total_conditions = 0
        self._current_condition = 0

    monkeypatch.setattr(plot_gui.PlotGeneratorWindow, "_finish_all", fake_finish, raising=False)

    def sync_start(self):
        if not self._conditions_queue:
            self._finish_all()
            return
        folder, out_dir, x_min, x_max, y_min, y_max, group_kwargs = self._gen_params
        condition = self._conditions_queue.pop(0)
        self._current_condition += 1
        cond_out = Path(out_dir)
        title = condition if self._all_conditions else self.title_edit.text()
        worker = plot_worker._Worker(
            folder,
            condition,
            self.roi_map,
            self.roi_combo.currentText(),
            title,
            self.xlabel_edit.text(),
            self.ylabel_edit.text(),
            x_min,
            x_max,
            y_min,
            y_max,
            str(cond_out),
            self.stem_color,
            **group_kwargs,
        )
        self._worker = worker
        self._thread = None
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._generation_finished)
        worker.run()

    monkeypatch.setattr(plot_gui.PlotGeneratorWindow, "_start_next_condition", sync_start, raising=False)

    return data_store, plot_records


def _build_plot_project(
    tmp_path: Path,
    *,
    groups: dict | None = None,
    participants: dict | None = None,
    subjects: list[str],
    conditions: list[str],
) -> tuple[Path, Path]:
    root = tmp_path / "plot_proj"
    root.mkdir()
    excel_root = root / EXCEL_SUBFOLDER_NAME
    excel_root.mkdir()
    manifest: dict[str, object] = {"name": "Plot"}
    if groups:
        manifest["groups"] = groups
    if participants:
        manifest["participants"] = participants
    (root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    for cond in conditions:
        cond_dir = excel_root / cond
        cond_dir.mkdir(parents=True, exist_ok=True)
        for pid in subjects:
            (cond_dir / f"{pid}_{cond}_Results.xlsx").write_text("", encoding="utf-8")
    return root, excel_root


@pytest.mark.qt
def test_plot_generator_single_group_defaults(qtbot, tmp_path, monkeypatch, plot_smoke_env):
    (data_store, plot_records) = plot_smoke_env
    project_root, excel_root = _build_plot_project(tmp_path, subjects=["P01"], conditions=["CondA"])
    output_dir = tmp_path / "plots"
    output_dir.mkdir()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No, raising=False)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok, raising=False)

    win = plot_gui.PlotGeneratorWindow(project_dir=str(project_root))
    qtbot.addWidget(win)
    win.folder_edit.setText(str(excel_root))
    win._populate_conditions(str(excel_root))
    win.out_edit.setText(str(output_dir))

    assert not win.group_box.isVisible()

    data_store["subjects"] = {"CondA": {"P01": {"ROI": [1.0, 2.0]}}}

    win.condition_combo.setCurrentText("CondA")
    win._generate()

    assert plot_records
    assert plot_records[-1]["group_curves"] == {}


@pytest.mark.qt
def test_plot_generator_multigroup_overlay(qtbot, tmp_path, monkeypatch, plot_smoke_env):
    (data_store, plot_records) = plot_smoke_env
    groups = {"GroupA": {}, "GroupB": {}}
    participants = {"P01": {"group": "GroupA"}, "P02": {"group": "GroupB"}}
    project_root, excel_root = _build_plot_project(
        tmp_path,
        subjects=["P01", "P02"],
        conditions=["CondA"],
        groups=groups,
        participants=participants,
    )
    output_dir = tmp_path / "plots"
    output_dir.mkdir()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No, raising=False)

    win = plot_gui.PlotGeneratorWindow(project_dir=str(project_root))
    qtbot.addWidget(win)
    win.folder_edit.setText(str(excel_root))
    win._populate_conditions(str(excel_root))
    win.out_edit.setText(str(output_dir))

    assert win.group_box.isVisible()

    win.group_overlay_check.setChecked(True)
    item = win.group_list.item(0)
    item.setCheckState(Qt.Unchecked)

    data_store["subjects"] = {
        "CondA": {
            "P01": {"ROI": [1.0, 2.0]},
            "P02": {"ROI": [3.0, 4.0]},
        }
    }

    win.condition_combo.setCurrentText("CondA")
    win._generate()

    curves = plot_records[-1]["group_curves"]
    assert list(curves.keys()) == [win.group_list.item(1).text()]


@pytest.mark.qt
def test_plot_generator_unassigned_subjects_logged(qtbot, tmp_path, monkeypatch, plot_smoke_env):
    (data_store, plot_records) = plot_smoke_env
    groups = {"GroupA": {}, "GroupB": {}}
    participants = {"P01": {"group": "GroupA"}, "P02": {"group": "GroupB"}}
    project_root, excel_root = _build_plot_project(
        tmp_path,
        subjects=["P01", "P02", "P03"],
        conditions=["CondA"],
        groups=groups,
        participants=participants,
    )
    output_dir = tmp_path / "plots"
    output_dir.mkdir()

    win = plot_gui.PlotGeneratorWindow(project_dir=str(project_root))
    qtbot.addWidget(win)
    win.folder_edit.setText(str(excel_root))
    win._populate_conditions(str(excel_root))
    win.out_edit.setText(str(output_dir))

    win.group_overlay_check.setChecked(True)

    data_store["subjects"] = {
        "CondA": {
            "P01": {"ROI": [1.0, 2.0]},
            "P02": {"ROI": [3.0, 4.0]},
            "P03": {"ROI": [5.0, 6.0]},
        }
    }

    win.condition_combo.setCurrentText("CondA")
    win._generate()

    log_text = win.log.toPlainText()
    assert "lack group assignments" in log_text
    curves = plot_records[-1]["group_curves"]
    assert set(curves.keys()) == {"GroupA", "GroupB"}
    assert plot_records[-1]["freqs"]
