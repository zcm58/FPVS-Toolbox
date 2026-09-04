from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _source(relative_path: str) -> str:
    path = REPO_ROOT / relative_path
    source = path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(path))
    return source


def test_settings_and_processing_inputs_carry_all_recording_qc_keys() -> None:
    settings_source = _source("src/Main_App/gui/settings_panel.py")
    inputs_source = _source("src/Main_App/gui/processing_inputs.py")
    canonical_keys = (
        "manual_removed_electrodes_by_recording",
        "manual_excluded_recordings",
        "manual_excluded_recording_conditions",
    )

    for key in canonical_keys:
        assert key in settings_source
        assert key in inputs_source
    assert "recording_rows=recording_rows" in settings_source
    assert "excluded_recording_conditions=" in settings_source


def test_recording_qc_surfaces_disclose_visit_identity_and_fixed_order_risk() -> None:
    workflow_source = _source("src/Main_App/gui/preprocessing_qc_workflow.py")
    removed_source = _source(
        "src/Main_App/gui/manual_removed_electrodes_dialog.py"
    )
    exclusion_source = _source(
        "src/Main_App/gui/manual_participant_exclusions_dialog.py"
    )

    assert "Session / phase-at-visit" in workflow_source
    assert "fixed order can" in workflow_source
    assert "Participant (all visits)" in workflow_source
    assert "Session / phase-at-visit" in removed_source
    assert "Session / phase-at-visit" in exclusion_source
    assert "Missing / not registered" in _source(
        "src/Main_App/gui/recording_qc_identity.py"
    )


def test_embedded_repeated_qc_tables_use_compact_reachable_layout() -> None:
    workflow_source = _source("src/Main_App/gui/preprocessing_qc_workflow.py")

    assert workflow_source.count("compact_rows=True") >= 1
    assert "compact_rows=recording_mode" in workflow_source
    assert workflow_source.count("_install_preflight_cell_widget(") >= 4
    assert "widget.hide()" in workflow_source
    assert "horizontal_scroll.setValue(horizontal_scroll.minimum())" in workflow_source


def test_settings_exposes_project_owned_experimental_qc_without_legacy_mode() -> None:
    settings_source = _source("src/Main_App/gui/settings_panel.py")
    schema_source = _source("src/Main_App/projects/experimental_qc_settings.py")

    assert 'tabs.addTab(tab, "Experimental")' in settings_source
    assert '"Off (recommended)"' in settings_source
    assert '"On"' in settings_source
    assert '"Manual list"' not in settings_source
    assert "MANUAL_REMOVED_ELECTRODES_ENABLED_KEY" in settings_source
    assert "update_experimental_qc_settings" in settings_source
    assert "SUMMED_BCA_SCREENING_BRIEF_TEXT" in settings_source
    assert "development experience and are not validated for every protocol" in (
        schema_source
    )
    assert "check does not remove data by itself" in schema_source


def test_expected_matrix_is_frozen_before_generated_outputs_are_changed() -> None:
    workflow_source = _source("src/Main_App/gui/processing_workflows.py")

    prepare_start = workflow_source.index("def _prepare_excel_outputs_for_plan(")
    callback_call = workflow_source.index("before_mutation()", prepare_start)
    first_cleanup = min(
        workflow_source.index("clean_managed_excel_root(", prepare_start),
        workflow_source.index("clean_participant_outputs(", prepare_start),
    )
    assert callback_call < first_cleanup
    start = workflow_source.index("def start_processing(")
    assert workflow_source.index("before_mutation=lambda:", start) > start
    assert workflow_source.index("_freeze_expected_processing_matrix(", start) > start
    assert "save_expected_recording_condition_plan" in workflow_source


def test_reprocessing_scope_extends_existing_reviewed_marker_plans() -> None:
    processing_source = _source("src/Main_App/gui/processing_workflows.py")
    qc_source = _source("src/Main_App/gui/preprocessing_qc_workflow.py")

    assert "_additional_preflight_infos_for_chosen_scope" in processing_source
    assert "preserve_existing_plans=True" in processing_source
    assert "preserve_existing_plans: bool = False" in qc_source
    assert "existing_event_plans.update(current_event_plans)" in qc_source
