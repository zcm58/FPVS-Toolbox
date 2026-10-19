from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.processing.hardware_capabilities import spatial_tool_unavailable_reason


BP = {"preprocessing": {"hardware_platform": "brain_products", "hardware_confirmed": True}}


@pytest.mark.parametrize("tool", ["LORETA Visualizer", "Scalp Maps", "Free Harmonic Clustering Analysis"])
def test_fixed_spatial_methods_require_qualified_hardware(tool):
    assert "BioSemi64" in spatial_tool_unavailable_reason(BP, tool)
    assert "Brain Products" in spatial_tool_unavailable_reason(SimpleNamespace(preprocessing=BP["preprocessing"]), tool)
    assert spatial_tool_unavailable_reason({}, tool) == ""


@pytest.mark.parametrize("settings", [
    {"hardware_platform": "brain_products"},
    {"hardware_platform": "brain_products", "hardware_confirmed": True,
     "initial_reference": "channels", "initial_reference_channels": []},
])
def test_spatial_tool_explanation_does_not_require_complete_processing_setup(settings):
    assert "Brain Products" in spatial_tool_unavailable_reason(settings, "Scalp Maps")


@pytest.mark.parametrize("tool", ["Standard FPVS Screening", "SNR", "Individual Detectability", "Stats"])
def test_nonspatial_tools_remain_available(tool):
    assert spatial_tool_unavailable_reason(BP, tool) == ""


def test_scalp_map_public_loader_rejects_brain_products_before_any_channels(tmp_path, monkeypatch):
    from Main_App.projects import DatasetIndexError
    from Tools.Publication_Maps import excel_inputs

    monkeypatch.setattr(excel_inputs, "load_project_dataset_index", lambda _: SimpleNamespace(manifest=BP))
    with pytest.raises(DatasetIndexError, match="Brain Products"):
        excel_inputs.load_publication_dataset_index(tmp_path)


@pytest.mark.parametrize("selector", ["_select_cohort", "_select_repeated_batch_cohort"])
def test_fhc_all_cohort_routes_reject_unqualified_hardware_before_reading(tmp_path, selector):
    from Tools.Free_Harmonic_Clustering import inputs
    from Tools.Free_Harmonic_Clustering.models import FreeHarmonicInputError

    with pytest.raises(FreeHarmonicInputError, match="Brain Products"):
        getattr(inputs, selector)(SimpleNamespace(manifest=BP), None, tmp_path)


@pytest.mark.parametrize("module_name,function", [
    ("project_inputs", "build_l2_mne_conditions_from_project"),
    ("project_fullfft_inputs", "build_l2_mne_hauk_zscore_conditions_from_project"),
    ("project_fullfft_inputs", "build_l2_mne_hauk_participant_zscore_conditions_from_project"),
])
def test_loreta_workbook_inputs_reject_same_labels_from_unqualified_hardware(tmp_path, monkeypatch, module_name, function):
    from importlib import import_module

    module = import_module(f"Tools.LORETA_Visualizer.source_producers.{module_name}")
    monkeypatch.setattr(module, "load_project_dataset_index", lambda _: SimpleNamespace(manifest=BP))
    with pytest.raises(ValueError, match="Brain Products"):
        getattr(module, function)(tmp_path)


def test_loreta_time_domain_inputs_reject_unqualified_hardware(tmp_path, monkeypatch):
    from Tools.LORETA_Visualizer.source_producers import project_time_domain_inputs as module

    monkeypatch.setattr(module, "load_project_manifest_for_dataset_path", lambda _: BP)
    with pytest.raises(module.ProjectTimeDomainInputError, match="Brain Products"):
        module.load_project_time_domain_inputs(
            tmp_path, expected_inputs=(), expected_processing_fingerprint="x",
            expected_processing_fingerprint_version="v1",
        )


def test_main_window_launches_consult_shared_hardware_capability_without_loading_gui():
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "src/Main_App/gui/main_window.py").read_text(encoding="utf-8"))
    methods = {node.name: ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert "spatial_tool_available" in methods["open_free_harmonic_clustering"]
    assert "spatial_tool_available" in methods["_frequency_domain_outputs_ready_for_tool"]
