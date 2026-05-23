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
    assert config.include_scalp_maps is False
    assert config.scalp_vmin == -1.0
    assert config.scalp_vmax == 1.0
    assert config.scalp_title_a_template == "{condition} {roi} scalp map"
    assert config.scalp_title_b_template == "{condition} {roi} scalp map"
    assert config.legend_custom_enabled is False
    assert config.legend_condition_a is None
    assert config.legend_condition_b is None
    assert config.legend_a_peaks is None
    assert config.legend_b_peaks is None
    assert config.project_root is None


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
        include_scalp_maps=True,
        scalp_vmin=-2.0,
        scalp_vmax=2.0,
        scalp_title_a_template="A {condition}",
        scalp_title_b_template="B {condition}",
        legend_custom_enabled=True,
        legend_condition_a="Custom A",
        legend_condition_b="Custom B",
        legend_a_peaks="A peaks",
        legend_b_peaks="B peaks",
        project_root=str(tmp_path),
    )

    assert isinstance(worker.config, PlotWorkerConfig)
    assert worker.config.condition_b == "CondB"
    assert worker.config.overlay is True
    assert worker.config.include_scalp_maps is True
    assert worker.config.project_root == str(tmp_path)
    assert worker.stem_color == "green"
    assert worker.stem_color_b == "purple"
    assert worker.oddballs == [1.0, 2.0]
    assert worker.subject_groups == {"P01": "Group A"}
    assert worker.selected_groups == ["Group A"]
    assert worker.enable_group_overlay is True
    assert worker.multi_group_mode is True
    assert worker.scalp_title_a_template == "A {condition}"
    assert worker.legend_custom_enabled is True
