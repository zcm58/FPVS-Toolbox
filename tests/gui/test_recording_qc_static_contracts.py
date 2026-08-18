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
