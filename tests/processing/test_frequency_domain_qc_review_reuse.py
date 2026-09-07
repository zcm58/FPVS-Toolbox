"""A saved review follows scientific inputs across harmonic-cache refreshes."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from Main_App.processing import frequency_domain_qc as frequency_qc
from Main_App.processing import full_fft_provenance, harmonic_selection_qc
from Main_App.projects.preprocessing_settings import (
    FIXED_HARMONIC_SELECTION_PROFILE,
    HARMONIC_SELECTION_PROFILE_VERSION,
)
from Tools.Stats.analysis.dv_policy_group_significant import (
    clear_group_significant_selection_cache,
)
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_PREDEFINED_POLICY_NAME,
    GROUP_SIGNIFICANT_POLICY_NAME,
    HARMONIC_PROFILE_LEGACY_ID,
)
from Tools.Stats.data import group_harmonic_cache
from tests.processing.test_frequency_domain_qc import _decisions, _make_project


@pytest.fixture
def adaptive_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # These small spectral workbooks omit the upstream processing receipts. The
    # real selection, cache, finding generation, and review persistence all run.
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_workbook_geometry",
        lambda _root, *, dataset_index=None: {},
    )
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_full_fft_provenance",
        lambda _root, *, dataset_index=None: object(),
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O2"], "Central": ["PZ"]},
    )
    project = _make_project(tmp_path)
    preprocessing = dict(project.preprocessing)
    preprocessing.update(
        harmonic_selection_policy=GROUP_SIGNIFICANT_POLICY_NAME,
        harmonic_selection_profile=HARMONIC_PROFILE_LEGACY_ID,
        harmonic_selection_profile_version=HARMONIC_SELECTION_PROFILE_VERSION,
    )
    project.update_preprocessing(preprocessing)
    project.save()
    frequencies = [round(index * 0.1, 4) for index in range(641)]
    full_fft = pd.DataFrame(
        {
            f"{frequency:.4f}_Hz": [
                20.0 if frequency in (1.2, 2.4) else (1.2 if index % 2 else 0.8)
            ] * 2
            for index, frequency in enumerate(frequencies)
        },
        index=["O2", "PZ"],
    )
    full_fft.index.name = "Electrode"
    for path in (project.project_root / "1 - Excel Data Files").rglob("*.xlsx"):
        with pd.ExcelWriter(path, engine="openpyxl", mode="a") as writer:
            full_fft.to_excel(writer, sheet_name="FullFFT Amplitude (uV)")
    clear_group_significant_selection_cache()
    yield project
    clear_group_significant_selection_cache()


def test_accepting_retain_reuses_review_after_real_adaptive_cache_refresh(
    adaptive_project, monkeypatch,
):
    project = adaptive_project
    cache_time = ["2026-09-07T12:00:00Z"]
    monkeypatch.setattr(group_harmonic_cache, "_now_utc_iso", lambda: cache_time[0])
    first = frequency_qc.run_frequency_domain_qc_review(project)
    assert first["review_required"] is True
    accepted = frequency_qc.apply_frequency_domain_qc_decision(
        project.project_root,
        first,
        review_decisions=_decisions(first, frequency_qc.DECISION_RETAIN),
    )

    # Applying the review changes the durable harmonic-cache request's QC
    # signature. The resumed worker therefore recomputes the same selection.
    cache_time[0] = "2026-09-07T12:01:00Z"
    resumed = frequency_qc.run_frequency_domain_qc_review(project)
    assert resumed["provisional_harmonic_metadata"]["selection_cache_key"] != (
        first["provisional_harmonic_metadata"]["selection_cache_key"]
    )
    assert resumed["provisional_harmonic_metadata"]["selection_cache_saved_at"] != (
        first["provisional_harmonic_metadata"]["selection_cache_saved_at"]
    )
    assert resumed["review_findings"] == first["review_findings"]
    assert resumed["selected_harmonics_hz"] == first["selected_harmonics_hz"]
    assert resumed["analysis_fingerprint"] == first["analysis_fingerprint"]
    assert resumed["review_required"] is False
    assert resumed["review_reused"] is True
    assert resumed["current_decision_fingerprint"] == accepted["last_review"][
        "decision_fingerprint"
    ]

    # A new worker/process may read the durable cache rather than its in-memory
    # counterpart. That operational difference must not reopen the same review.
    clear_group_significant_selection_cache()
    reloaded = frequency_qc.run_frequency_domain_qc_review(project)
    assert reloaded["provisional_harmonic_metadata"]["selection_cache_source"] == (
        "saved_project_metadata"
    )
    assert reloaded["analysis_fingerprint"] == first["analysis_fingerprint"]
    assert reloaded["review_required"] is False
    assert reloaded["review_reused"] is True


def _report_with_old_cache_sensitive_hash(project, monkeypatch):
    current_analysis_fingerprint = frequency_qc._analysis_fingerprint
    current_hash_payload = frequency_qc._hash_payload

    def old_analysis_fingerprint(**kwargs):
        # Before the fix, the entire raw provisional metadata was hashed into
        # analysis identity, including cache source, key, and save time.
        def old_hash_payload(payload):
            if "provisional_harmonic_metadata" in payload and "workbooks" in payload:
                payload = {
                    **payload,
                    "provisional_harmonic_metadata": frequency_qc._json_safe(
                        kwargs["provisional_metadata"],
                    ),
                }
            return current_hash_payload(payload)

        with monkeypatch.context() as legacy:
            legacy.setattr(frequency_qc, "_hash_payload", old_hash_payload)
            return current_analysis_fingerprint(**kwargs)

    with monkeypatch.context() as legacy:
        legacy.setattr(frequency_qc, "_analysis_fingerprint", old_analysis_fingerprint)
        return frequency_qc.run_frequency_domain_qc_review(project)


@pytest.mark.parametrize("change", ["source_values", "selection_profile"])
def test_saved_review_with_old_cache_sensitive_hash_survives_resume_and_sync(
    adaptive_project, monkeypatch, change,
):
    project = adaptive_project
    original = _report_with_old_cache_sensitive_hash(project, monkeypatch)
    frequency_qc.apply_frequency_domain_qc_decision(
        project.project_root,
        original,
        review_decisions=_decisions(original, frequency_qc.DECISION_RETAIN),
    )
    old_evidence = frequency_qc.load_frequency_domain_qc_state(
        project.project_root,
    )["review_evidence"]

    for _ in range(2):
        clear_group_significant_selection_cache()
        resumed = frequency_qc.run_frequency_domain_qc_review(project)
        assert resumed["analysis_fingerprint"] == original["analysis_fingerprint"]
        assert resumed["review_required"] is False
        assert resumed["review_reused"] is True
        synced = frequency_qc.sync_frequency_domain_qc_automatic_state(
            project.project_root, resumed,
        )
        assert synced["review_evidence"] == old_evidence
        assert frequency_qc.resolve_frequency_qc_coverage_decisions(
            project.project_root,
        ).review_complete is True
    _change_review_inputs(project, change)
    changed = frequency_qc.run_frequency_domain_qc_review(project)
    assert changed["analysis_fingerprint"] != original["analysis_fingerprint"]
    assert changed["review_required"] is True
    assert changed["review_reused"] is False


@pytest.mark.parametrize("mutation", ["evidence_payload", "analysis_fingerprint"])
def test_old_review_compatibility_rejects_damaged_receipt(
    adaptive_project, monkeypatch, mutation,
):
    project = adaptive_project
    original = _report_with_old_cache_sensitive_hash(project, monkeypatch)
    frequency_qc.apply_frequency_domain_qc_decision(
        project.project_root,
        original,
        review_decisions=_decisions(original, frequency_qc.DECISION_RETAIN),
    )
    manifest_path = project.project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    state = manifest["tools"]["frequency_domain_qc"]
    if mutation == "evidence_payload":
        state["review_evidence"]["provisional_harmonic_metadata"][
            "selection_cache_key"
        ] = "altered_without_rehashing"
    else:
        state["last_review"]["analysis_fingerprint"] = "mismatched_analysis_identity"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    current = frequency_qc.run_frequency_domain_qc_review(project)
    assert current["analysis_fingerprint"] != original["analysis_fingerprint"]
    assert current["review_required"] is True
    assert current["review_reused"] is False


@pytest.mark.parametrize("change", ["source_values", "selection_profile"])
def test_changed_review_inputs_still_require_review(adaptive_project, change):
    project = adaptive_project
    first = frequency_qc.run_frequency_domain_qc_review(project)
    frequency_qc.apply_frequency_domain_qc_decision(
        project.project_root,
        first,
        review_decisions=_decisions(first, frequency_qc.DECISION_RETAIN),
    )
    _change_review_inputs(project, change)

    changed = frequency_qc.run_frequency_domain_qc_review(project)
    assert changed["analysis_fingerprint"] != first["analysis_fingerprint"]
    assert changed["review_required"] is True
    assert changed["review_reused"] is False


def _change_review_inputs(project, change):
    if change == "source_values":
        path = (
            project.project_root / "1 - Excel Data Files" / "CondA"
            / "P1_CondA_Results.xlsx"
        )
        frame = pd.read_excel(path, sheet_name="BCA (uV)")
        frame.loc[frame["Electrode"] == "O2", "1.2000_Hz"] = 160.0
        with pd.ExcelWriter(
            path, engine="openpyxl", mode="a", if_sheet_exists="replace",
        ) as writer:
            frame.to_excel(writer, sheet_name="BCA (uV)", index=False)
    else:
        preprocessing = dict(project.preprocessing)
        preprocessing.update(
            harmonic_selection_policy=FIXED_PREDEFINED_POLICY_NAME,
            harmonic_selection_profile=FIXED_HARMONIC_SELECTION_PROFILE,
        )
        project.update_preprocessing(preprocessing)
        project.save()


def test_changed_exclusion_context_settles_after_one_reconfirmation(adaptive_project):
    project = adaptive_project
    first = frequency_qc.run_frequency_domain_qc_review(project)
    frequency_qc.apply_frequency_domain_qc_decision(
        project.project_root,
        first,
        review_decisions=_decisions(
            first, frequency_qc.DECISION_EXCLUDE_CONDITION,
        ),
    )
    changed = frequency_qc.run_frequency_domain_qc_review(project)
    assert changed["analysis_fingerprint"] != first["analysis_fingerprint"]
    assert changed["review_required"] is True
    assert changed["reconfirmation_findings"]
    frequency_qc.apply_frequency_domain_qc_decision(
        project.project_root,
        changed,
        review_decisions=_decisions(
            changed, frequency_qc.DECISION_EXCLUDE_CONDITION,
        ),
    )

    settled = frequency_qc.run_frequency_domain_qc_review(project)
    assert settled["analysis_fingerprint"] == changed["analysis_fingerprint"]
    assert settled["review_required"] is False
    assert frequency_qc.active_frequency_domain_exclusions(
        project.project_root
    ).excluded_participant_conditions == {("P1", "CondA")}


def _retain_retired_electrode_reconfirmation(project, monkeypatch):
    first = frequency_qc.run_frequency_domain_qc_review(project)
    # Build the valid receipt produced when electrode exclusion was supported.
    # Current production choices must continue rejecting this retired action.
    with monkeypatch.context() as legacy:
        legacy.setattr(
            frequency_qc, "REVIEW_DECISIONS",
            (*frequency_qc.REVIEW_DECISIONS,
             frequency_qc.DECISION_EXCLUDE_CONDITION_ELECTRODE),
        )
        frequency_qc.apply_frequency_domain_qc_decision(
            project.project_root, first,
            review_decisions=_decisions(
                first, frequency_qc.DECISION_EXCLUDE_CONDITION_ELECTRODE,
            ),
        )
    review = frequency_qc.run_frequency_domain_qc_review(project)
    assert review["review_required"] is True
    assert review["reconfirmation_findings"]
    assert review["flags"]  # Ordinary findings coexist with the reconfirmations.
    frequency_qc.apply_frequency_domain_qc_decision(
        project.project_root, review,
        review_decisions=_decisions(review, frequency_qc.DECISION_RETAIN),
    )
    accepted = frequency_qc.load_frequency_domain_qc_state(project.project_root)
    return review, accepted


@pytest.mark.parametrize("change", ["source_values", "selection_profile"])
def test_resolved_retain_reconfirmation_does_not_reopen_unchanged_findings(
    adaptive_project, monkeypatch, change,
):
    project = adaptive_project
    reviewed, accepted = _retain_retired_electrode_reconfirmation(project, monkeypatch)
    resolved_fingerprints = {
        finding["finding_fingerprint"]
        for finding in reviewed["reconfirmation_findings"]
    }
    for _ in range(3):
        clear_group_significant_selection_cache()
        resumed = frequency_qc.run_frequency_domain_qc_review(project)
        assert resumed["analysis_fingerprint"] == reviewed["analysis_fingerprint"]
        assert resumed["reconfirmation_findings"] == []
        assert resumed["flags"] == reviewed["flags"]
        assert len(resumed["review_decisions"]) == len(resumed["review_findings"])
        assert resolved_fingerprints.isdisjoint(
            finding["finding_fingerprint"] for finding in resumed["review_findings"]
        )
        assert resumed["review_required"] is False
        assert resumed["review_reused"] is True
        assert resumed["current_decision_fingerprint"] == accepted["last_review"][
            "decision_fingerprint"
        ]
        synced = frequency_qc.sync_frequency_domain_qc_automatic_state(
            project.project_root, resumed,
        )
        assert synced["review_decisions"] == accepted["review_decisions"]
        assert synced["review_evidence"] == accepted["review_evidence"]
        assert frequency_qc.resolve_frequency_qc_coverage_decisions(
            project.project_root,
        ).review_complete is True
    _change_review_inputs(project, change)
    changed = frequency_qc.run_frequency_domain_qc_review(project)
    assert changed["analysis_fingerprint"] != reviewed["analysis_fingerprint"]
    assert changed["review_required"] is True
    assert changed["review_reused"] is False
    assert resolved_fingerprints.isdisjoint(
        row["finding_fingerprint"] for row in changed["active_review_decisions"]
    )


@pytest.mark.parametrize("mutation", ["evidence", "decision"])
def test_resolved_reconfirmation_reuse_rejects_tampered_receipts(
    adaptive_project, monkeypatch, mutation,
):
    project = adaptive_project
    _retain_retired_electrode_reconfirmation(project, monkeypatch)
    manifest_path = project.project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    state = manifest["tools"]["frequency_domain_qc"]
    if mutation == "evidence":
        state["review_evidence"]["screening_status"] = "tampered"
    else:
        resolved = next(
            row for row in state["review_decisions"]
            if row.get("replaces_decision_fingerprint")
        )
        resolved["reason"] = "altered_without_rehashing"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    resumed = frequency_qc.run_frequency_domain_qc_review(project)
    assert resumed["review_required"] is True
    assert resumed["review_reused"] is False
