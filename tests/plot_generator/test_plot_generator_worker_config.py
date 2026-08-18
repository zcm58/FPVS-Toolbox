from pathlib import Path

import pytest

from Main_App.projects import ProjectDatasetIndex
from Tools.Plot_Generator import analysis_context
from Tools.Plot_Generator.worker import _Worker
from Tools.Plot_Generator.worker_config import PlotWorkerConfig


def _config_kwargs(tmp_path):
    return {
        "folder": str(tmp_path),
        "condition": "CondA",
        "roi_map": {"ROI": ["Cz"]},
        "selected_roi": "ROI",
        "title": "Title",
        "xlabel": "Hz",
        "ylabel": "SNR",
        "x_min": 0.0,
        "x_max": 10.0,
        "y_min": 0.0,
        "y_max": 3.0,
        "out_dir": str(tmp_path / "plots"),
    }


def test_worker_config_defaults_match_worker_constructor(tmp_path) -> None:
    config = PlotWorkerConfig(**_config_kwargs(tmp_path))

    assert config.stem_color == "red"
    assert config.condition_b is None
    assert config.stem_color_b == "blue"
    assert config.oddballs is None
    assert config.use_matlab_style is False
    assert config.overlay is False
    assert config.subject_groups is None
    assert config.selected_groups is None
    assert config.enable_group_overlay is False
    assert config.multi_group_mode is False
    assert config.legend_custom_enabled is False
    assert config.legend_condition_a is None
    assert config.legend_condition_b is None
    assert config.legend_a_peaks is None
    assert config.legend_b_peaks is None
    assert config.project_root is None
    assert config.spectral_qc_enabled is True
    assert config.prepared_dataset_index is None


def test_worker_keeps_public_constructor_and_stores_config_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(_Worker, "_read_analysis_float", lambda self, option, fallback: fallback)

    worker = _Worker(
        **_config_kwargs(tmp_path),
        stem_color="GREEN",
        condition_b="CondB",
        stem_color_b="PURPLE",
        oddballs=[1.0, "bad", 2.0, -1.0],
        use_matlab_style=True,
        overlay=True,
        subject_groups={"p01": "Group A", "p02": None, 3: "Group B"},
        selected_groups=["Group A", ""],
        enable_group_overlay=True,
        multi_group_mode=True,
        legend_custom_enabled=True,
        legend_condition_a="Custom A",
        legend_condition_b="Custom B",
        legend_a_peaks="A peaks",
        legend_b_peaks="B peaks",
        project_root=str(tmp_path),
        spectral_qc_enabled=False,
    )

    assert isinstance(worker.config, PlotWorkerConfig)
    assert worker.config.condition_b == "CondB"
    assert worker.config.overlay is True
    assert worker.config.project_root == str(tmp_path)
    assert worker.stem_color == "green"
    assert worker.stem_color_b == "purple"
    assert worker.oddballs == [1.0, 2.0]
    assert worker.subject_groups == {"P01": "Group A"}
    assert worker.selected_groups == ["Group A"]
    assert worker.enable_group_overlay is True
    assert worker.multi_group_mode is True
    assert worker.legend_custom_enabled is True
    assert worker.spectral_qc_enabled is False


def _empty_index(root: Path) -> ProjectDatasetIndex:
    return ProjectDatasetIndex(
        project_root=root,
        excel_root=root,
        scan_root=root,
        manifest=None,
        groups={},
        participants={},
        workbooks=(),
        excluded_workbooks=(),
        diagnostics=(),
    )


def test_worker_reuses_prepared_dataset_index_without_rescanning(
    tmp_path,
    monkeypatch,
) -> None:
    index = _empty_index(tmp_path.resolve())
    worker = _Worker(
        **_config_kwargs(tmp_path),
        spectral_qc_enabled=False,
        prepared_dataset_index=index,
    )
    configured: list[ProjectDatasetIndex] = []
    monkeypatch.setattr(
        analysis_context,
        "load_project_dataset_index",
        lambda _folder: (_ for _ in ()).throw(
            AssertionError("prepared index must avoid a second scan")
        ),
    )
    monkeypatch.setattr(
        worker,
        "_configure_analysis_context",
        lambda value: configured.append(value),
    )

    loaded = worker._load_dataset_index()

    assert loaded is index
    assert worker._dataset_index is index
    assert worker._dataset_index_loaded is True
    assert configured == [index]
    monkeypatch.setattr(worker, "_run", lambda: None)
    payloads: list[dict] = []
    worker.finished.connect(payloads.append)

    worker.run()

    assert payloads[0]["_prepared_dataset_index"] is index


def test_worker_rejects_prepared_index_from_another_input_folder(
    tmp_path,
) -> None:
    selected = tmp_path / "selected"
    selected.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    worker = _Worker(
        **_config_kwargs(selected),
        spectral_qc_enabled=False,
        prepared_dataset_index=_empty_index(other.resolve()),
    )

    with pytest.raises(RuntimeError, match="does not belong to the selected"):
        worker._load_dataset_index()
