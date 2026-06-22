from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Tools.LORETA_Visualizer.gui import (
    DEFAULT_STACKED_CORTICAL_ZSCORE_SCALAR_RANGE,
    PROJECT_SOURCE_EXPORT_ALL_ZSCORE,
    PROJECT_SOURCE_EXPORT_DEFAULT_MODES,
    PROJECT_SOURCE_EXPORT_ELORETA_VOLUME,
    PROJECT_SOURCE_EXPORT_HAUK_ZSCORE,
    PROJECT_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST,
    PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST,
    ProjectSourceMapExportBatchResult,
    ProjectSourceMapExportWorker,
    SOURCE_METHOD_ELORETA_VOLUME,
    SOURCE_METHOD_L2_MNE_SURFACE,
    SOURCE_SUMMARY_MEDIAN,
    SOURCE_SUMMARY_RAW_MEAN,
    SOURCE_SUMMARY_TRIMMED_MEAN,
    _activation_display_payload,
    _coerce_existing_project_root,
    _group_manifest_conditions,
    _group_manifest_methods,
    _ordered_source_summary_ids,
    _project_root_from_object,
    _project_source_export_failure_text,
    _source_summary_label,
    _source_export_status_text,
    default_stacked_split_figure_export_path,
    default_split_figure_export_path,
    default_project_source_manifest_paths,
    default_project_zscore_manifest_path,
    resolve_loreta_import_start_dir,
    split_figure_condition_code,
    split_figure_condition_display_label,
)
from Tools.LORETA_Visualizer.fsaverage_cache import (
    DEFAULT_FSAVERAGE_SUBJECTS_DIR,
    candidate_fsaverage_subjects_dirs,
    default_fsaverage_subjects_dir,
    ensure_allowed_fsaverage_subjects_dir,
    fetch_fsaverage_subjects_dir,
    fpvs_toolbox_root,
)
from Tools.LORETA_Visualizer import fsaverage_mesh
from Tools.LORETA_Visualizer.prepared_payload_validator import validate_prepared_source_manifest_json
from Tools.LORETA_Visualizer.prepared_payload_importer import PreparedSourceManifestEntry
from Tools.LORETA_Visualizer.source_payloads import make_source_payload
from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_export import (
    DEFAULT_PROJECT_ELORETA_VOLUME_MANIFEST_NAME,
    default_project_eloreta_volume_output_dir,
)
from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import L2MNECorticalForwardModel
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_zscore_export import (
    DEFAULT_PROJECT_HAUK_ZSCORE_MANIFEST_NAME,
    PROJECT_L2_MNE_HAUK_ZSCORE_OUTPUT_FOLDER,
)
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
    PROJECT_L2_MNE_BETA_OUTPUT_FOLDER,
    PROJECT_SOURCE_LOCALIZATION_FOLDER,
    _resolve_fsaverage_subjects_dir,
    _surface_source_points_and_faces,
    default_project_l2_mne_output_dir,
    write_project_l2_mne_cortical_surface_payloads,
)


def test_project_l2_mne_export_writes_manifest_and_payloads_under_project_root(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = write_project_l2_mne_cortical_surface_payloads(
        project_root=project_root,
        forward_model=_tiny_forward_model(),
    )

    assert result.output_dir == default_project_l2_mne_output_dir(project_root)
    assert result.manifest_path.is_file()
    assert result.producer_result.manifest_validation.label == validate_prepared_source_manifest_json(
        result.manifest_path,
        require_payload_files=True,
    ).label
    assert len(result.producer_result.payloads) == 2
    assert result.project_inputs.selected_harmonics_hz == (2.4, 4.8)

    raw_manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert raw_manifest["label"] == "L2-MNE cortical-surface beta source maps"
    assert [entry["label"] for entry in raw_manifest["conditions"]] == ["Condition A", "Condition B"]

    first_payload = json.loads(result.producer_result.payloads[0].payload_path.read_text(encoding="utf-8"))
    metadata = first_payload["metadata"]
    assert first_payload["coordinate_space"] == "fsaverage_surface"
    assert metadata["config_project_integration"] == "phase_6c_project_l2_mne_beta"
    assert metadata["config_project_root_name"] == "Project"
    assert metadata["config_source_topography_metric"] == "bca"
    assert metadata["condition_project_input_assembly"] == "phase_6b_read_only"


def test_project_l2_mne_export_rejects_outputs_outside_project_root(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    with pytest.raises(ValueError, match="inside the project root"):
        write_project_l2_mne_cortical_surface_payloads(
            project_root=project_root,
            output_dir=tmp_path / "outside",
            forward_model=_tiny_forward_model(),
        )


def test_default_fsaverage_cache_is_root_local(monkeypatch) -> None:
    monkeypatch.delenv("FPVS_FSAVERAGE_SUBJECTS_DIR", raising=False)
    monkeypatch.delenv("SUBJECTS_DIR", raising=False)

    class FakeMneConfig:
        @staticmethod
        def get_config(key: str) -> None:
            return None

    expected = fpvs_toolbox_root() / DEFAULT_FSAVERAGE_SUBJECTS_DIR

    assert default_fsaverage_subjects_dir() == expected
    assert candidate_fsaverage_subjects_dirs(FakeMneConfig())[0] == expected


def test_fsaverage_cache_ignores_stale_mne_config_under_src(monkeypatch) -> None:
    monkeypatch.delenv("FPVS_FSAVERAGE_SUBJECTS_DIR", raising=False)
    monkeypatch.delenv("SUBJECTS_DIR", raising=False)
    root = fpvs_toolbox_root()
    expected = root / DEFAULT_FSAVERAGE_SUBJECTS_DIR

    class FakeMneConfig:
        @staticmethod
        def get_config(key: str) -> str | None:
            if key == "SUBJECTS_DIR":
                return str(root / "src")
            return None

    assert candidate_fsaverage_subjects_dirs(FakeMneConfig())[0] == expected
    assert fetch_fsaverage_subjects_dir() == expected


def test_fsaverage_cache_rejects_source_and_docs_paths() -> None:
    root = fpvs_toolbox_root()

    with pytest.raises(ValueError, match="src/ or docs"):
        ensure_allowed_fsaverage_subjects_dir(root / "src" / "fsaverage-cache")
    with pytest.raises(ValueError, match="src/ or docs"):
        ensure_allowed_fsaverage_subjects_dir(root / "docs" / "fsaverage-cache")


def test_project_forward_model_fetches_fsaverage_to_root_local_cache(monkeypatch, tmp_path) -> None:
    import mne.datasets

    target_subjects_dir = tmp_path / "repo-cache" / "mne" / "MNE-fsaverage-data"
    (target_subjects_dir / "fsaverage").mkdir(parents=True)
    calls: list[Path] = []

    def fake_fetch_fsaverage(*, subjects_dir: Path | None = None, verbose: bool | None = None) -> Path:
        del verbose
        assert subjects_dir is not None
        subjects_path = Path(subjects_dir)
        calls.append(subjects_path)
        fsaverage_dir = subjects_path / "fsaverage"
        fsaverage_dir.mkdir(parents=True, exist_ok=True)
        return fsaverage_dir

    class FakeMneConfig:
        @staticmethod
        def get_config(key: str) -> None:
            return None

    monkeypatch.setattr(
        "Tools.LORETA_Visualizer.source_producers.project_l2_mne_export.preferred_fsaverage_subjects_dirs",
        lambda: [target_subjects_dir],
    )
    monkeypatch.setattr(
        "Tools.LORETA_Visualizer.source_producers.project_l2_mne_export.fetch_fsaverage_subjects_dir",
        lambda: target_subjects_dir,
    )
    monkeypatch.setattr(mne.datasets, "fetch_fsaverage", fake_fetch_fsaverage)

    assert _resolve_fsaverage_subjects_dir(FakeMneConfig(), allow_fetch=True) == target_subjects_dir
    assert calls == [target_subjects_dir]


def test_mesh_loader_fetches_fsaverage_to_root_local_cache(monkeypatch, tmp_path) -> None:
    import mne.datasets

    target_subjects_dir = tmp_path / "repo-cache" / "mne" / "MNE-fsaverage-data"
    (target_subjects_dir / "fsaverage").mkdir(parents=True)
    calls: list[Path] = []

    def fake_fetch_fsaverage(*, subjects_dir: Path | None = None, verbose: bool | None = None) -> Path:
        del verbose
        assert subjects_dir is not None
        subjects_path = Path(subjects_dir)
        calls.append(subjects_path)
        fsaverage_dir = subjects_path / "fsaverage"
        fsaverage_dir.mkdir(parents=True, exist_ok=True)
        return fsaverage_dir

    monkeypatch.setattr(fsaverage_mesh, "preferred_fsaverage_dirs", lambda: [target_subjects_dir / "fsaverage"])
    monkeypatch.setattr(fsaverage_mesh, "fetch_fsaverage_subjects_dir", lambda: target_subjects_dir)
    monkeypatch.setattr(mne.datasets, "fetch_fsaverage", fake_fetch_fsaverage)

    assert fsaverage_mesh._resolve_fsaverage_dir(allow_fetch=True) == target_subjects_dir / "fsaverage"
    assert calls == [target_subjects_dir]


def test_loreta_import_dialog_prefers_last_dir_then_project_source_dir(tmp_path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    zscore_dir = project_root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_L2_MNE_HAUK_ZSCORE_OUTPUT_FOLDER
    zscore_dir.mkdir(parents=True)
    amplitude_dir = project_root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_L2_MNE_BETA_OUTPUT_FOLDER
    amplitude_dir.mkdir(parents=True)
    last_dir = tmp_path / "last"
    last_dir.mkdir()

    assert resolve_loreta_import_start_dir(project_root=project_root, last_import_dir=last_dir) == str(last_dir)
    assert resolve_loreta_import_start_dir(project_root=project_root, last_import_dir=None) == str(zscore_dir)

    zscore_dir.rmdir()
    assert resolve_loreta_import_start_dir(project_root=project_root, last_import_dir=None) == str(amplitude_dir)

    amplitude_dir.rmdir()
    amplitude_dir.parent.rmdir()
    assert resolve_loreta_import_start_dir(project_root=project_root, last_import_dir=None) == str(project_root)
    assert resolve_loreta_import_start_dir(project_root=None, last_import_dir=None) == ""


def test_loreta_split_figure_export_path_prefers_project_source_dir(tmp_path) -> None:
    project_root = tmp_path / "Project"
    zscore_dir = project_root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_L2_MNE_HAUK_ZSCORE_OUTPUT_FOLDER
    zscore_dir.mkdir(parents=True)

    path = default_split_figure_export_path(
        project_root=project_root,
        last_import_dir=None,
        condition_label="Semantic Response 2",
    )

    assert path == str(zscore_dir / "loreta_split_hemispheres_Semantic_Response_2.pdf")


def test_loreta_stacked_split_figure_export_path_uses_cr_sr_codes(tmp_path) -> None:
    project_root = tmp_path / "Project"
    zscore_dir = project_root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_L2_MNE_HAUK_ZSCORE_OUTPUT_FOLDER
    zscore_dir.mkdir(parents=True)

    path = default_stacked_split_figure_export_path(
        project_root=project_root,
        last_import_dir=None,
        top_condition_label="Color Response 2",
        bottom_condition_label="Semantic Response",
    )

    assert path == str(zscore_dir / "loreta_split_hemispheres_CR_SR.pdf")


def test_loreta_split_figure_condition_code_labels_color_and_semantic_responses() -> None:
    assert split_figure_condition_code("Color Response") == "CR"
    assert split_figure_condition_code("Semantic Response 2") == "SR"
    assert split_figure_condition_code("Oddball Baseline") == "OB"


def test_loreta_split_figure_display_labels_write_out_color_and_semantic_responses() -> None:
    assert split_figure_condition_display_label("Color Response 2") == "Color Response"
    assert split_figure_condition_display_label("Semantic Response Raw mean z-score") == "Semantic Response"
    assert split_figure_condition_display_label("Oddball Baseline") == "Oddball Baseline"
    assert DEFAULT_STACKED_CORTICAL_ZSCORE_SCALAR_RANGE == (0.0, 3.5)


def test_loreta_manifest_conditions_group_participant_summary_entries(tmp_path) -> None:
    entries = (
        PreparedSourceManifestEntry(
            condition_id="manifest:1:color_response_mean",
            label="Color Response Raw mean z-score",
            payload_path=tmp_path / "color_mean.json",
            metadata={"participant_zscore_aggregation": "mean"},
        ),
        PreparedSourceManifestEntry(
            condition_id="manifest:2:color_response_median",
            label="Color Response Median z-score",
            payload_path=tmp_path / "color_median.json",
            metadata={"participant_zscore_aggregation": "median"},
        ),
        PreparedSourceManifestEntry(
            condition_id="manifest:3:color_response_trimmed_mean",
            label="Color Response 20% trimmed mean z-score",
            payload_path=tmp_path / "color_trimmed.json",
            metadata={"participant_zscore_aggregation": "trimmed_mean"},
        ),
        PreparedSourceManifestEntry(
            condition_id="manifest:4:semantic_response_raw_mean",
            label="Semantic Response Raw mean z-score",
            payload_path=tmp_path / "semantic_mean.json",
            metadata={"participant_zscore_aggregation": "mean"},
        ),
    )

    groups = _group_manifest_conditions(entries)

    assert list(groups) == ["color_response", "semantic_response"]
    assert groups["color_response"].label == "Color Response"
    assert _ordered_source_summary_ids(groups["color_response"]) == (
        SOURCE_SUMMARY_RAW_MEAN,
        SOURCE_SUMMARY_MEDIAN,
        SOURCE_SUMMARY_TRIMMED_MEAN,
    )
    assert (
        groups["color_response"].entries_by_summary[SOURCE_SUMMARY_RAW_MEAN].condition_id
        == "manifest:1:color_response_mean"
    )
    assert groups["semantic_response"].entries_by_summary[SOURCE_SUMMARY_RAW_MEAN].condition_id == (
        "manifest:4:semantic_response_raw_mean"
    )
    assert _source_summary_label(SOURCE_SUMMARY_TRIMMED_MEAN) == "20% trimmed mean z-score"


def test_loreta_manifest_methods_group_l2_and_eloreta_entries_separately(tmp_path) -> None:
    entries = (
        PreparedSourceManifestEntry(
            condition_id="manifest:1:color_response_mean",
            label="Color Response Raw mean z-score",
            payload_path=tmp_path / "color_l2_mean.json",
            metadata={
                "producer_method": "l2_mne_fsaverage_participant_zscore_mean",
                "participant_zscore_aggregation": "mean",
            },
        ),
        PreparedSourceManifestEntry(
            condition_id="manifest:1:color_response_mean",
            label="Color Response eLORETA volume Raw mean z-score",
            payload_path=tmp_path / "color_eloreta_mean.json",
            metadata={
                "source_method": "eloreta_volume",
                "producer_method": "eloreta_volume_participant_zscore_mean",
                "participant_zscore_aggregation": "mean",
            },
        ),
    )

    groups = _group_manifest_methods(entries)

    assert set(groups) == {SOURCE_METHOD_L2_MNE_SURFACE, SOURCE_METHOD_ELORETA_VOLUME}
    assert list(groups[SOURCE_METHOD_L2_MNE_SURFACE].condition_groups) == ["color_response"]
    assert list(groups[SOURCE_METHOD_ELORETA_VOLUME].condition_groups) == ["color_response"]


def test_volume_display_payload_uses_source_cluster_mask_then_positive_exploratory_values() -> None:
    payload = make_source_payload(
        points=np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float),
        values=np.asarray([-1.0, 0.5, 3.0], dtype=float),
        label="eLORETA volume",
        kind="volume_points",
        source_model="eloreta_volume_participant_zscore_mean",
        value_label="source-space z-score",
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_source_indices": [0, 2],
        },
        normalize_values=False,
    )

    masked = _activation_display_payload(payload, transparent_mesh_display=True, use_cluster_mask=True)
    exploratory = _activation_display_payload(payload, transparent_mesh_display=True, use_cluster_mask=False)

    assert masked.values.tolist() == [-1.0, 3.0]
    assert masked.metadata["display_value_filter"] == "cluster_mask"
    assert exploratory.values.tolist() == [0.5, 3.0]
    assert exploratory.metadata["display_value_filter_threshold"] == 0.0


def test_default_project_zscore_manifest_path_requires_existing_manifest(tmp_path) -> None:
    project_root = tmp_path / "Project"
    zscore_dir = project_root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_L2_MNE_HAUK_ZSCORE_OUTPUT_FOLDER
    zscore_dir.mkdir(parents=True)
    manifest_path = zscore_dir / DEFAULT_PROJECT_HAUK_ZSCORE_MANIFEST_NAME

    assert default_project_zscore_manifest_path(project_root) is None

    manifest_path.write_text("{}", encoding="utf-8")
    assert default_project_zscore_manifest_path(project_root) == manifest_path


def test_default_project_source_manifest_paths_returns_l2_then_eloreta(tmp_path) -> None:
    project_root = tmp_path / "Project"
    zscore_dir = project_root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_L2_MNE_HAUK_ZSCORE_OUTPUT_FOLDER
    eloreta_dir = default_project_eloreta_volume_output_dir(project_root)
    zscore_dir.mkdir(parents=True)
    eloreta_dir.mkdir(parents=True)
    zscore_manifest = zscore_dir / DEFAULT_PROJECT_HAUK_ZSCORE_MANIFEST_NAME
    eloreta_manifest = eloreta_dir / DEFAULT_PROJECT_ELORETA_VOLUME_MANIFEST_NAME

    zscore_manifest.write_text("{}", encoding="utf-8")
    eloreta_manifest.write_text("{}", encoding="utf-8")

    assert default_project_source_manifest_paths(project_root) == (zscore_manifest, eloreta_manifest)


def test_loreta_project_root_resolver_reads_current_project(tmp_path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()

    class ProjectLike:
        def __init__(self, root: Path) -> None:
            self.project_root = root

    class HostLike:
        def __init__(self, project: ProjectLike) -> None:
            self.currentProject = project

    assert _project_root_from_object(HostLike(ProjectLike(project_root))) == project_root.resolve()


def test_loreta_project_root_resolver_ignores_empty_string() -> None:
    assert _coerce_existing_project_root("") is None


def test_source_export_status_text_reports_flagged_participant_choice() -> None:
    assert _source_export_status_text(
        PROJECT_SOURCE_EXPORT_ALL_ZSCORE,
        automatic=True,
        include_flagged_subjects=False,
    ) == "Preparing L2-MNE surface and eLORETA volume source-space z-score maps (excluding flagged participants)..."

    assert _source_export_status_text(
        PROJECT_SOURCE_EXPORT_ALL_ZSCORE,
        automatic=False,
        include_flagged_subjects=True,
    ) == "Building L2-MNE surface and eLORETA volume source-space z-score maps (including flagged participants)..."

    assert _source_export_status_text(
        PROJECT_SOURCE_EXPORT_HAUK_ZSCORE,
        automatic=False,
        include_flagged_subjects=True,
    ) == "Building participant-first source-space z-score JSON from the active project (including flagged participants)..."

    assert _source_export_status_text(
        PROJECT_SOURCE_EXPORT_HAUK_ZSCORE,
        automatic=True,
        include_flagged_subjects=False,
    ) == "Preparing participant-first project source-space z-score maps (excluding flagged participants)..."

    assert _source_export_status_text(
        PROJECT_SOURCE_EXPORT_HAUK_ZSCORE,
        automatic=False,
        include_flagged_subjects=False,
        zscore_model=PROJECT_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST,
    ) == "Building deprecated group-first source-space z-score JSON from the active project (excluding flagged participants)..."
    assert _source_export_status_text(
        PROJECT_SOURCE_EXPORT_ELORETA_VOLUME,
        automatic=False,
        include_flagged_subjects=False,
    ) == "Building beta eLORETA volume source-space z-score JSON from the active project (excluding flagged participants)..."


def _fake_source_export_result(output_dir: Path, *, method_id: str, payload_count: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        output_dir=output_dir,
        manifest_path=output_dir / "manifest.json",
        producer_result=SimpleNamespace(
            method_id=method_id,
            payloads=tuple(SimpleNamespace() for _index in range(payload_count)),
        ),
        project_inputs=SimpleNamespace(flagged_subjects=(), excluded_subjects=()),
        export_model=PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST,
    )


def test_project_source_export_worker_rebuilds_l2_and_eloreta_batch(tmp_path, monkeypatch) -> None:
    from Tools.LORETA_Visualizer.source_producers import project_eloreta_volume_export
    from Tools.LORETA_Visualizer.source_producers import project_l2_mne_hauk_zscore_export

    calls: list[tuple[str, bool, str | None]] = []

    def fake_l2_export(**kwargs):
        calls.append(("l2", kwargs["include_flagged_subjects"], kwargs["zscore_model"]))
        kwargs["progress_callback"]("l2 done")
        return _fake_source_export_result(tmp_path / "l2", method_id="l2_mne_fsaverage_participant_zscore", payload_count=2)

    def fake_eloreta_export(**kwargs):
        calls.append(("eloreta", kwargs["include_flagged_subjects"], kwargs.get("zscore_model")))
        kwargs["progress_callback"]("eloreta done")
        return _fake_source_export_result(
            tmp_path / "eloreta",
            method_id="eloreta_volume_participant_zscore",
            payload_count=3,
        )

    monkeypatch.setattr(project_l2_mne_hauk_zscore_export, "write_project_l2_mne_hauk_zscore_payloads", fake_l2_export)
    monkeypatch.setattr(project_eloreta_volume_export, "write_project_eloreta_volume_hauk_zscore_payloads", fake_eloreta_export)
    worker = ProjectSourceMapExportWorker(
        project_root=tmp_path,
        export_modes=PROJECT_SOURCE_EXPORT_DEFAULT_MODES,
        include_flagged_subjects=True,
        zscore_model=PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST,
    )
    progress_messages: list[str] = []
    exported: list[object] = []
    failed: list[str] = []
    worker.progress.connect(progress_messages.append)
    worker.exported.connect(exported.append)
    worker.failed.connect(failed.append)

    worker.run()

    assert failed == []
    assert calls == [
        ("l2", True, PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST),
        ("eloreta", True, None),
    ]
    assert len(exported) == 1
    result = exported[0]
    assert isinstance(result, ProjectSourceMapExportBatchResult)
    assert result.requested_modes == PROJECT_SOURCE_EXPORT_DEFAULT_MODES
    assert len(result.results) == 2
    assert result.failures == ()
    assert "Building L2-MNE surface source maps (1/2)" in progress_messages[0]
    assert any("Building eLORETA volume source maps (2/2)" in message for message in progress_messages)


def test_project_source_export_worker_reports_partial_batch_failure(tmp_path, monkeypatch) -> None:
    from Tools.LORETA_Visualizer.source_producers import project_eloreta_volume_export
    from Tools.LORETA_Visualizer.source_producers import project_l2_mne_hauk_zscore_export

    def fake_l2_export(**kwargs):
        return _fake_source_export_result(tmp_path / "l2", method_id="l2_mne_fsaverage_participant_zscore")

    def fake_eloreta_export(**_kwargs):
        raise RuntimeError("missing volume model")

    monkeypatch.setattr(project_l2_mne_hauk_zscore_export, "write_project_l2_mne_hauk_zscore_payloads", fake_l2_export)
    monkeypatch.setattr(project_eloreta_volume_export, "write_project_eloreta_volume_hauk_zscore_payloads", fake_eloreta_export)
    worker = ProjectSourceMapExportWorker(
        project_root=tmp_path,
        export_modes=PROJECT_SOURCE_EXPORT_DEFAULT_MODES,
        include_flagged_subjects=False,
        zscore_model=PROJECT_ZSCORE_MODEL_PARTICIPANT_FIRST,
    )
    exported: list[object] = []
    failed: list[str] = []
    worker.exported.connect(exported.append)
    worker.failed.connect(failed.append)

    worker.run()

    assert failed == []
    assert len(exported) == 1
    result = exported[0]
    assert isinstance(result, ProjectSourceMapExportBatchResult)
    assert len(result.results) == 1
    assert len(result.failures) == 1
    assert result.failures[0].export_mode == PROJECT_SOURCE_EXPORT_ELORETA_VOLUME
    assert result.failures[0].message == "missing volume model"


def test_project_source_export_failure_text_guides_stats_ready_prerequisites() -> None:
    message = (
        "Stats-ready workbook is required for selected harmonics: "
        "D:\\FPVS Toolbox Project Root\\Project\\3 - Statistical Analysis Results\\Stats_Ready_Summed_BCA.xlsx"
    )

    text = _project_source_export_failure_text(message)

    assert text.startswith("Project source maps are not ready yet.")
    assert "Re-run preprocessing for this project" in text
    assert "Export Stats-Ready Workbook" in text
    assert "Details: Stats-ready workbook is required" in text


def test_project_source_export_failure_text_guides_fullfft_prerequisites() -> None:
    message = (
        "Phase 6D source-space z-score mode requires the 'FullFFT Amplitude (uV)' sheet "
        "in every included participant workbook. Missing in: SCP1_Condition_Results.xlsx."
    )

    text = _project_source_export_failure_text(message)

    assert text.startswith("Project source maps are not ready yet.")
    assert "Re-run preprocessing for this project" in text
    assert "Export Stats-Ready Workbook" in text
    assert "FullFFT Amplitude (uV)" in text


def test_project_source_export_failure_text_guides_missing_fullfft_workbooks() -> None:
    message = "No included FullFFT workbooks were found for source-space z-score assembly."

    text = _project_source_export_failure_text(message)

    assert text.startswith("Project source maps are not ready yet.")
    assert "Re-run preprocessing for this project" in text
    assert "Export Stats-Ready Workbook" in text
    assert message in text


def test_project_source_export_failure_text_preserves_unrecognized_error() -> None:
    assert (
        _project_source_export_failure_text("Unable to build MNE/fsaverage forward model")
        == "Project source export failed: Unable to build MNE/fsaverage forward model"
    )


def test_source_points_use_native_coordinate_source_space_not_forward_head_space() -> None:
    forward_space = {
        "vertno": np.asarray([0, 1, 2], dtype=np.int64),
        "rr": np.asarray(
            [
                [10.0, 10.0, 10.0],
                [20.0, 20.0, 20.0],
                [30.0, 30.0, 30.0],
            ],
            dtype=float,
        ),
        "use_tris": np.asarray([[0, 1, 2]], dtype=np.int64),
    }
    native_space = {
        "vertno": np.asarray([0, 1, 2], dtype=np.int64),
        "rr": np.asarray(
            [
                [-0.040, -0.090, 0.020],
                [0.000, -0.100, 0.030],
                [0.040, -0.090, 0.020],
            ],
            dtype=float,
        ),
    }

    points, faces, counts, vertex_ids, hemispheres = _surface_source_points_and_faces(
        [forward_space],
        coordinate_source_spaces=[native_space],
    )

    assert np.allclose(
        points,
        np.asarray(
            [
                [-40.0, -90.0, 20.0],
                [0.0, -100.0, 30.0],
                [40.0, -90.0, 20.0],
            ]
        ),
    )
    assert np.array_equal(faces, np.asarray([[0, 1, 2]], dtype=np.int64))
    assert counts == (3,)
    assert vertex_ids == (0, 1, 2)
    assert hemispheres == ("lh", "lh", "lh")


def _tiny_forward_model() -> L2MNECorticalForwardModel:
    leadfield = np.vstack(
        [
            np.linspace(0.1 + channel * 0.01, 0.4 + channel * 0.01, 4)
            for channel in range(len(DEFAULT_ELECTRODE_NAMES_64))
        ]
    )
    return L2MNECorticalForwardModel(
        channel_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
        source_points=np.asarray(
            [
                [-40.0, -80.0, 20.0],
                [-10.0, -90.0, 32.0],
                [10.0, -90.0, 32.0],
                [40.0, -80.0, 20.0],
            ],
            dtype=float,
        ),
        leadfield=leadfield,
        faces=np.asarray([[0, 1, 2], [1, 3, 2]], dtype=np.int64),
        metadata={"fixture": True, "forward_model_status": "tiny test model"},
    )


def _build_project_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "Project"
    stats_dir = project_root / "3 - Statistical Analysis Results"
    excel_root = project_root / "1 - Excel Data Files"
    stats_dir.mkdir(parents=True)
    excel_root.mkdir(parents=True)
    _write_stats_ready(stats_dir / "Stats_Ready_Summed_BCA.xlsx")
    pd.DataFrame({"participant_id": [], "exclusion_reason": []}).to_excel(
        stats_dir / "Excluded Participants.xlsx",
        sheet_name="Excluded Participants",
        index=False,
    )
    pd.DataFrame({"participant_id": [], "flag_types": []}).to_excel(
        stats_dir / "Flagged Participants.xlsx",
        sheet_name="Flag Summary",
        index=False,
    )
    for condition, base in (("Condition A", 10.0), ("Condition B", 100.0)):
        condition_dir = excel_root / condition
        condition_dir.mkdir()
        for subject_offset, subject in enumerate(("SCP1", "SCP2")):
            _write_participant_workbook(
                condition_dir / f"{subject}_{condition}_Results.xlsx",
                base=base + subject_offset,
            )
    return project_root


def _write_stats_ready(path: Path) -> None:
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(
            {
                "condition": ["Condition A", "Condition A", "Condition B", "Condition B"],
                "subject_id": ["P1", "P2", "P1", "P2"],
                "roi": ["ROI"] * 4,
                "summed_bca_uv": [1.0, 2.0, 3.0, 4.0],
            }
        ).to_excel(writer, sheet_name="Long_Format", index=False)
        pd.DataFrame(
            {
                "harmonic_hz": [1.2, 2.4, 4.8],
                "selected": [False, True, True],
            }
        ).to_excel(writer, sheet_name="Harmonic_Selection", index=False)


def _write_participant_workbook(path: Path, *, base: float) -> None:
    bca = pd.DataFrame(
        {
            "Electrode": DEFAULT_ELECTRODE_NAMES_64,
            "2.4000_Hz": [base + index for index in range(64)],
            "4.8000_Hz": [base + 10.0 + index for index in range(64)],
        }
    )
    with pd.ExcelWriter(path) as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)", index=False)
