"""Catch unusable processing geometry before asking users to review findings."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS, biosemi64_geometry_identity
from Main_App.processing import full_fft_provenance
from Main_App.processing.frequency_domain_qc import (
    FrequencyDomainCoverageDecisions,
    mark_frequency_domain_outputs_stale,
)
from tests.processing.test_processing_full_fft_provenance import (
    _managed_full_fft_project,
    _write_geometry_ledger,
)


def test_pre_review_geometry_does_not_require_frequency_decisions(tmp_path):
    root = _managed_full_fft_project(tmp_path)
    mark_frequency_domain_outputs_stale(root, reason="Review is still pending.")
    original_manifest = (root / "project.json").read_bytes()

    assert full_fft_provenance.require_current_project_pre_review_geometry(root) == (
        biosemi64_geometry_identity()
    )
    assert (root / "project.json").read_bytes() == original_manifest


@pytest.mark.parametrize("valid_review", [True, False])
def test_pre_review_geometry_honors_only_valid_reviewed_cohort_exclusions(
    tmp_path, monkeypatch, valid_review,
):
    root = _managed_full_fft_project(tmp_path)
    incompatible = biosemi64_geometry_identity(electrode_mapping_profile="biosemi64_1020_ab_v1")
    _write_geometry_ledger(root, {"P1": biosemi64_geometry_identity(), "P2": incompatible})
    decisions = FrequencyDomainCoverageDecisions(
        decision_fingerprint="valid-reviewed-cohort",
        review_complete=True,
        excluded_participants=frozenset({"P2"}),
        excluded_recordings=frozenset(),
        excluded_participant_conditions=frozenset(),
        excluded_recording_conditions=frozenset(),
        excluded_electrodes_by_participant_condition={},
        excluded_electrodes_by_recording_condition={},
        reviewed_decisions=(),
    )
    monkeypatch.setattr(
        full_fft_provenance, "resolve_frequency_qc_coverage_decisions",
        lambda _root: replace(decisions, review_complete=valid_review),
    )
    if valid_review:
        assert full_fft_provenance.require_current_project_pre_review_geometry(root) == (
            biosemi64_geometry_identity()
        )
    else:
        with pytest.raises(full_fft_provenance.FullFftProvenanceError, match="mixed electrode geometries"):
            full_fft_provenance.require_current_project_pre_review_geometry(root)


def test_pre_review_geometry_names_saved_and_requested_mapping(tmp_path):
    root = _managed_full_fft_project(tmp_path)
    manifest_path = root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preprocessing"]["electrode_mapping_profile"] = "biosemi64_1020_ab_v1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(full_fft_provenance.FullFftProvenanceError) as caught:
        full_fft_provenance.require_current_project_pre_review_geometry(root)
    message = str(caught.value)
    assert "anatomical_labels" in message
    assert "biosemi64_1020_ab_v1" in message
    assert "Settings > Preprocessing > Channel mapping profile" in message
    assert "Restore the original mapping setting" in message


@pytest.mark.parametrize("damage", ["coordinates", "retained_subset", "missing_ledger"])
def test_pre_review_geometry_keeps_source_validation_strict(tmp_path, damage):
    root = _managed_full_fft_project(tmp_path)
    geometry = biosemi64_geometry_identity()
    if damage == "coordinates":
        geometry["coordinate_fingerprint"] = "unknown_coordinates"
        _write_geometry_ledger(root, {"P1": geometry, "P2": geometry})
    elif damage == "retained_subset":
        geometry = biosemi64_geometry_identity(retained_channels=BIOSEMI64_CHANNELS[1:])
        _write_geometry_ledger(root, {"P1": geometry, "P2": geometry})
    else:
        (root / ".fpvs_processing" / "processing_ledger.json").unlink()

    with pytest.raises(full_fft_provenance.FullFftProvenanceError):
        full_fft_provenance.require_current_project_pre_review_geometry(root)


def test_pre_review_geometry_respects_preprocessing_manual_exclusion(tmp_path):
    root = _managed_full_fft_project(tmp_path)
    invalid = biosemi64_geometry_identity()
    invalid["coordinate_fingerprint"] = "stale_excluded_participant"
    _write_geometry_ledger(root, {"P1": biosemi64_geometry_identity(), "P2": invalid})
    manifest_path = root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preprocessing"]["manual_excluded_participants"] = ["P2"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert full_fft_provenance.require_current_project_pre_review_geometry(root) == (
        biosemi64_geometry_identity()
    )


def test_stale_full_fft_error_keeps_original_failure_reason(tmp_path):
    root = _managed_full_fft_project(tmp_path)
    reason = "Processed workbooks use anatomical labels; project requests A/B labels."
    mark_frequency_domain_outputs_stale(root, reason=reason)

    with pytest.raises(full_fft_provenance.FullFftProvenanceStaleError) as caught:
        full_fft_provenance.require_current_project_workbook_geometry(root)
    assert reason in str(caught.value)
    assert "resume post-processing" in str(caught.value)
    assert "Complete the required post-processing review" not in str(caught.value)
