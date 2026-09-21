"""Headless checks for project-local future-run choices and worker adapters."""

from dataclasses import FrozenInstanceError
import json
from types import SimpleNamespace

import pytest

from Tools.Free_Harmonic_Clustering.gui.analysis_plan_state import (
    AnalysisPlanPreferences,
    AnalysisPlanStateError,
    load_analysis_plan_preferences,
    save_analysis_plan_preferences,
)
from Tools.Free_Harmonic_Clustering.gui.backend_adapter import FreeHarmonicBackendAdapter
from Tools.Free_Harmonic_Clustering.gui.exclusion_state import (
    load_project_recording_exclusions,
    save_project_recording_exclusions,
)
from Tools.Free_Harmonic_Clustering.gui.models import (
    AnalysisRecordingExclusion,
    GuiHarmonicMode,
    PlannedAnalysisSetup,
    ProjectFrequencySnapshot,
)


def test_plan_and_exclusion_preferences_never_overwrite_each_other(tmp_path):
    parent = tmp_path / "project" / "FHC results"
    assert load_analysis_plan_preferences(parent) is None
    choices = AnalysisPlanPreferences(("between_groups", "within_group_visits", "group_visit_change"))
    exclusion = AnalysisRecordingExclusion("P01_visit2", "Artifact")
    save_project_recording_exclusions(parent, (exclusion,))
    exclusion_bytes = (parent / "project_settings.json").read_bytes()
    plan_path = save_analysis_plan_preferences(parent, choices)
    assert (parent / "project_settings.json").read_bytes() == exclusion_bytes
    assert load_analysis_plan_preferences(parent) == choices
    plan_bytes = plan_path.read_bytes()
    save_project_recording_exclusions(parent, ())
    assert plan_path.read_bytes() == plan_bytes
    assert load_project_recording_exclusions(parent, ("P01_visit2",)) == ()
    save_analysis_plan_preferences(parent, AnalysisPlanPreferences(("between_conditions",), "reference", "Neutral"))
    assert load_project_recording_exclusions(parent, ("P01_visit2",)) == ()
    assert load_analysis_plan_preferences(parent).reference_condition == "Neutral"
    with pytest.raises(FrozenInstanceError):
        choices.condition_mode = "all_pairs"


@pytest.mark.parametrize("payload", [
    {"schema_version": 99, "families": ["between_groups"]},
    {"schema_version": 1, "families": "between_groups"},
    {"schema_version": 1, "families": ["unknown"]},
    {"schema_version": 1, "families": []},
    {"schema_version": 1, "families": ["between_groups", "between_groups"]},
])
def test_invalid_saved_plans_cannot_silently_become_default_runs(tmp_path, payload):
    (tmp_path / "analysis_plan.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AnalysisPlanStateError):
        load_analysis_plan_preferences(tmp_path)


def test_failed_atomic_plan_write_keeps_previous_choices(tmp_path, monkeypatch):
    from pathlib import Path

    previous = AnalysisPlanPreferences(("between_groups",))
    save_analysis_plan_preferences(tmp_path, previous)

    def fail_replace(*_args):
        raise PermissionError("Locked by another application")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(AnalysisPlanStateError, match="Locked"):
        save_analysis_plan_preferences(tmp_path, AnalysisPlanPreferences(("between_conditions",), "all_pairs"))
    assert load_analysis_plan_preferences(tmp_path) == previous


def test_planned_adapter_passes_the_frozen_plan_to_inference_and_export(tmp_path, monkeypatch):
    from Tools.Free_Harmonic_Clustering import planned_analysis, planned_exports

    plan = object()
    result = SimpleNamespace(plan=plan, outcomes=())
    receipt = object()
    calls = []

    def analyze(submitted, spec, **kwargs):
        calls.append((submitted, spec))
        kwargs["progress_callback"]("multiplicity", 3, 3)
        return result

    def publish(submitted, **kwargs):
        assert submitted is result
        assert not kwargs["cancel_check"]()
        return receipt

    monkeypatch.setattr(planned_analysis, "run_analysis_plan", analyze)
    monkeypatch.setattr(planned_exports, "export_analysis_plan_result", publish)
    progress = []
    outcome = FreeHarmonicBackendAdapter().run_planned_analysis(
        ProjectFrequencySnapshot(1.2, 6.0),
        PlannedAnalysisSetup(plan, GuiHarmonicMode.AUTOMATIC, None, 20.0),
        progress=lambda *args: progress.append(args), cancel_check=lambda: False,
    )
    assert calls[0][0] is plan
    assert outcome.result is result and outcome.receipt is receipt
    assert any("Holm" in message for _, _, message in progress)
