from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis.dv_policy_fixed_predefined import (
    build_fixed_harmonic_selection,
)
from Tools.Stats.analysis.dv_policy_group_significant import (
    build_group_significant_harmonic_selection,
)
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_HARMONIC_INPUT_UPPER_FREQUENCY,
    FIXED_HARMONIC_INPUT_UPPER_HARMONIC,
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN,
    HARMONIC_PROFILE_FIXED_ID,
    HARMONIC_PROFILE_LEGACY_ID,
    HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
    HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID,
    NEW_PROJECT_HARMONIC_PROFILE_ID,
    new_project_dv_policy_settings,
    normalize_dv_policy,
)
from Tools.Stats.analysis.harmonic_pooling import pool_group_condition_spectra
from Tools.Stats.data.group_harmonic_cache import build_group_harmonic_cache_request


def test_absent_settings_remain_legacy_but_new_project_default_is_explicit() -> None:
    assert normalize_dv_policy(None).harmonic_selection_profile == (
        HARMONIC_PROFILE_LEGACY_ID
    )
    new_settings = new_project_dv_policy_settings()
    assert NEW_PROJECT_HARMONIC_PROFILE_ID == (
        HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID
    )
    assert new_settings.harmonic_selection_profile == NEW_PROJECT_HARMONIC_PROFILE_ID
    assert new_settings.group_significant_electrode_scope == "all_scalp_electrodes"
    assert new_settings.group_significant_summation_method == "two_consecutive_failures"


def test_profile_version_and_frozen_mask_are_validated() -> None:
    with pytest.raises(ValueError, match="Unsupported harmonic-selection profile version"):
        normalize_dv_policy(
            {
                "harmonic_selection_profile": HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
                "harmonic_selection_profile_version": "99",
            }
        )
    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_dv_policy(
            {
                "harmonic_selection_profile": HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
                "group_significant_electrode_scope": (
                    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN
                ),
            }
        )
    settings = normalize_dv_policy(
        {
            "harmonic_selection_profile": HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
            "group_significant_electrode_scope": GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN,
            "group_significant_selection_electrodes": "oz, O1;OZ, o2",
        }
    )
    assert settings.group_significant_selection_electrodes == ("O1", "O2", "OZ")


def test_fixed_profile_rejects_unknown_input_mode_and_mandates_base_exclusion() -> None:
    with pytest.raises(ValueError, match="Unsupported fixed harmonic input mode"):
        normalize_dv_policy(
            {
                "harmonic_selection_profile": HARMONIC_PROFILE_FIXED_ID,
                "fixed_harmonic_input_mode": "guess_nearest_harmonics",
            }
        )

    selection = build_fixed_harmonic_selection(
        requested_values="1.2, 6.0, 7.2",
        bca_columns=["1.2000_Hz", "6.0000_Hz", "7.2000_Hz"],
        base_frequency_hz=6.0,
        auto_exclude_base_overlaps=False,
    )
    metadata = selection.to_metadata()
    assert selection.included_frequencies_hz == pytest.approx([1.2, 7.2])
    assert selection.excluded_base_overlap_frequencies_hz == pytest.approx([6.0])
    assert metadata["base_overlap_exclusion_requested"] is False
    assert metadata["base_overlap_exclusion_enabled"] is True
    assert metadata["base_overlap_exclusion_rule"] == (
        "mandatory_dynamic_base_frequency_multiples_v1"
    )


def test_balanced_pooling_uses_equal_groups_and_exports_effective_weights() -> None:
    spectra = {
        ("A1", "C1"): pd.Series([2.0, 4.0], index=[1.2, 2.4]),
        ("A2", "C1"): pd.Series([4.0, 6.0], index=[1.2, 2.4]),
        ("B1", "C1"): pd.Series([9.0, 11.0], index=[1.2, 2.4]),
    }
    pool = pool_group_condition_spectra(
        spectra=spectra,
        subjects=["A1", "A2", "B1"],
        conditions=["C1"],
        participant_group_ids={"A1": "A", "A2": "A", "B1": "B"},
        declared_group_ids=["A", "B"],
    )

    # Group A mean is [3, 5], Group B mean is [9, 11], then groups are 50/50.
    assert pool.condition_spectra["C1"].tolist() == pytest.approx([6.0, 8.0])
    cells = {(cell.group_id, cell.condition): cell for cell in pool.cells}
    assert cells[("A", "C1")].participant_count == 2
    assert cells[("A", "C1")].effective_participant_weight == pytest.approx(0.25)
    assert cells[("B", "C1")].participant_count == 1
    assert cells[("B", "C1")].effective_participant_weight == pytest.approx(0.5)


def test_balanced_pooling_blocks_an_entirely_missing_declared_cell() -> None:
    with pytest.raises(RuntimeError, match="B x C2"):
        pool_group_condition_spectra(
            spectra={
                ("A1", "C1"): pd.Series([1.0], index=[1.2]),
                ("A1", "C2"): pd.Series([1.0], index=[1.2]),
                ("B1", "C1"): pd.Series([1.0], index=[1.2]),
            },
            subjects=["A1", "B1"],
            conditions=["C1", "C2"],
            participant_group_ids={"A1": "A", "B1": "B"},
            declared_group_ids=["A", "B"],
        )


def test_two_failure_profile_stops_before_a_distant_detection_and_records_cells(
    tmp_path: Path,
) -> None:
    subjects = ["A1", "A2", "B1"]
    conditions = ["C1", "C2"]
    subject_data = _profile_workbooks(tmp_path, subjects, conditions)
    settings = normalize_dv_policy(
        {"harmonic_selection_profile": HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID}
    )

    selection = build_group_significant_harmonic_selection(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_frequency_hz=6.0,
        rois={"Posterior": ["O1"]},
        log_func=lambda _message: None,
        settings=settings,
        max_freq=4.8,
        participant_group_ids={"A1": "A", "A2": "A", "B1": "B"},
        declared_group_ids=["A", "B"],
    )

    assert selection.detected_significant_harmonics_hz == pytest.approx([1.2])
    assert selection.selected_harmonics_hz == pytest.approx([1.2])
    assert selection.harmonic_domain_hz == pytest.approx([1.2, 2.4, 3.6])
    assert selection.stopping_harmonics_hz == pytest.approx((2.4, 3.6))
    assert selection.stopping_reason == (
        "two_consecutive_eligible_harmonics_at_or_below_threshold"
    )
    assert selection.z_by_harmonic[1.2] == pytest.approx(
        np.mean(
            [
                selection.condition_z_by_harmonic[condition][1.2]
                for condition in conditions
            ]
        )
    )
    assert selection.selection_electrode_mask == ("O1",)
    distant = next(row for row in selection.rows if row.harmonic_index == 4)
    assert distant.evaluated is False
    assert distant.selected is False
    metadata = selection.to_metadata()
    assert metadata["evaluated_harmonics_hz"] == pytest.approx([1.2, 2.4, 3.6])
    assert metadata["detected_significant_harmonics_hz"] == pytest.approx([1.2])
    assert metadata["included_harmonics_hz"] == pytest.approx([1.2])
    assert metadata["pooling_cell_sample_sizes"] == {
        "A::C1": 2,
        "B::C1": 1,
        "A::C2": 2,
        "B::C2": 1,
    }
    assert len(metadata["selection_fingerprint"]) == 64


def test_significant_only_profile_keeps_distant_detection_without_fill(
    tmp_path: Path,
) -> None:
    subject_data = _profile_workbooks(tmp_path, ["S1"], ["C1", "C2"])
    selection = build_group_significant_harmonic_selection(
        subjects=["S1"],
        conditions=["C1", "C2"],
        subject_data=subject_data,
        base_frequency_hz=6.0,
        rois={"Posterior": ["O1"]},
        log_func=lambda _message: None,
        settings=normalize_dv_policy(
            {"harmonic_selection_profile": HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID}
        ),
        max_freq=4.8,
    )

    assert selection.detected_significant_harmonics_hz == pytest.approx([1.2, 4.8])
    assert selection.selected_harmonics_hz == pytest.approx([1.2, 4.8])
    assert all(row.evaluated for row in selection.rows)
    assert selection.to_metadata()["same_sample_adaptive"] is True


def test_two_failure_profile_blocks_when_search_ceiling_precedes_stopping_rule(
    tmp_path: Path,
) -> None:
    path = tmp_path / "alternating_peaks.xlsx"
    _write_profile_workbook(path, peak_harmonics=(1, 3))
    messages: list[str] = []
    with pytest.raises(RuntimeError, match="filter/Nyquist/neighbor-bin"):
        build_group_significant_harmonic_selection(
            subjects=["S1"],
            conditions=["C1"],
            subject_data={"S1": {"C1": str(path)}},
            base_frequency_hz=6.0,
            rois={"Posterior": ["O1"]},
            log_func=messages.append,
            settings=normalize_dv_policy(
                {
                    "harmonic_selection_profile": (
                        HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID
                    )
                }
            ),
            max_freq=3.6,
        )
    assert any("technical spectral support ended" in message for message in messages)


def test_two_failure_profile_skips_canonical_eligibility_hole(
    tmp_path: Path,
) -> None:
    path = tmp_path / "eligibility_hole.xlsx"
    frequencies = np.arange(0.0, 10.5 + 1e-9, 0.1)
    amplitudes = 1.0 + 0.05 * np.sin(np.arange(len(frequencies), dtype=float))
    amplitudes[12] = 10.0
    frame = pd.DataFrame(
        [["O1", *amplitudes]],
        columns=["Electrode", *[f"{frequency:.4f}_Hz" for frequency in frequencies]],
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="FullFFT Amplitude (uV)", index=False)

    selection = build_group_significant_harmonic_selection(
        subjects=["S1"],
        conditions=["C1"],
        subject_data={"S1": {"C1": str(path)}},
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
        eligible_harmonic_orders=[1, 3, 4],
        spectral_eligibility_fingerprint="eligibility-fixture",
        rois={"Posterior": ["O1"]},
        log_func=lambda _message: None,
        settings=normalize_dv_policy(
            {
                "harmonic_selection_profile": (
                    HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID
                )
            }
        ),
    )

    assert [row.harmonic_index for row in selection.rows if row.evaluated] == [1, 3, 4]
    assert selection.stopping_harmonics_hz == pytest.approx((3.6, 4.8))
    assert selection.eligible_harmonic_orders == (1, 3, 4)
    assert selection.spectral_eligibility_fingerprint == "eligibility-fixture"


def test_two_failure_profile_rejects_undefined_z_instead_of_counting_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "flat_noise.xlsx"
    frequencies = np.arange(0.0, 10.5 + 1e-9, 0.3)
    frame = pd.DataFrame(
        [["O1", *np.ones(len(frequencies), dtype=float)]],
        columns=["Electrode", *[f"{frequency:.4f}_Hz" for frequency in frequencies]],
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="FullFFT Amplitude (uV)", index=False)

    with pytest.raises(RuntimeError, match="undefined; an undefined value is not"):
        build_group_significant_harmonic_selection(
            subjects=["S1"],
            conditions=["C1"],
            subject_data={"S1": {"C1": str(path)}},
            base_frequency_hz=6.0,
            rois={"Posterior": ["O1"]},
            log_func=lambda _message: None,
            settings=normalize_dv_policy(
                {
                    "harmonic_selection_profile": (
                        HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID
                    )
                }
            ),
            max_freq=3.6,
        )


def test_frozen_mask_requires_every_non_qc_excluded_channel_per_workbook(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing_frozen_channel.xlsx"
    _write_profile_workbook(path)
    settings = normalize_dv_policy(
        {
            "harmonic_selection_profile": HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
            "group_significant_electrode_scope": (
                GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN
            ),
            "group_significant_selection_electrodes": ["O1", "O2"],
        }
    )

    with pytest.raises(RuntimeError, match=r"missing: O2.*QC electrode exclusion"):
        build_group_significant_harmonic_selection(
            subjects=["S1"],
            conditions=["C1"],
            subject_data={"S1": {"C1": str(path)}},
            base_frequency_hz=6.0,
            rois={"Posterior": ["O1"]},
            log_func=lambda _message: None,
            settings=settings,
            max_freq=4.8,
        )


def test_balanced_selection_and_fingerprint_ignore_discovery_order(tmp_path: Path) -> None:
    subjects = ["S1", "S2"]
    conditions = ["C1", "C2"]
    subject_data = _profile_workbooks(tmp_path, subjects, conditions)
    settings = normalize_dv_policy(
        {"harmonic_selection_profile": HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID}
    )

    def _build(subject_order: list[str], condition_order: list[str]):
        return build_group_significant_harmonic_selection(
            subjects=subject_order,
            conditions=condition_order,
            subject_data=subject_data,
            base_frequency_hz=6.0,
            rois={"Posterior": ["O1"]},
            log_func=lambda _message: None,
            settings=settings,
            max_freq=4.8,
        )

    forward = _build(subjects, conditions)
    reversed_order = _build(list(reversed(subjects)), list(reversed(conditions)))
    assert reversed_order.selected_harmonics_hz == pytest.approx(
        forward.selected_harmonics_hz
    )
    assert reversed_order.selection_fingerprint == forward.selection_fingerprint


def test_fixed_profile_supports_upper_harmonic_and_frequency_domains() -> None:
    columns = [f"{frequency:.4f}_Hz" for frequency in (1.2, 2.4, 3.6, 4.8, 6.0)]
    by_index = build_fixed_harmonic_selection(
        requested_values="",
        bca_columns=columns,
        base_frequency_hz=6.0,
        input_mode=FIXED_HARMONIC_INPUT_UPPER_HARMONIC,
        upper_harmonic_index=4,
    )
    by_frequency = build_fixed_harmonic_selection(
        requested_values="",
        bca_columns=columns,
        base_frequency_hz=6.0,
        input_mode=FIXED_HARMONIC_INPUT_UPPER_FREQUENCY,
        upper_frequency_hz=4.9,
    )
    assert by_index.included_frequencies_hz == pytest.approx([1.2, 2.4, 3.6, 4.8])
    assert by_frequency.included_frequencies_hz == pytest.approx([1.2, 2.4, 3.6, 4.8])
    assert by_index.to_metadata()["detected_significant_harmonics_hz"] == []
    assert by_index.to_metadata()["included_harmonics_hz"] == pytest.approx(
        [1.2, 2.4, 3.6, 4.8]
    )


def test_fixed_profile_preserves_declared_unavailable_harmonic_as_error() -> None:
    with pytest.raises(RuntimeError, match=r"4 Hz is unavailable.*was not reduced"):
        build_fixed_harmonic_selection(
            requested_values="2, 4, 6",
            bca_columns=["2_Hz", "4_Hz", "6_Hz"],
            base_frequency_hz=10.0,
            oddball_frequency_hz=2.0,
            eligible_harmonic_orders=[1, 3],
        )


def test_nonlegacy_cache_identity_records_profile_mask_and_canonical_groups(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.1.0",
                "preprocessing": {},
                "groups": {"A": {"label": "A"}, "B": {"label": "B"}},
                "participants": {
                    "A1": {"group_id": "A"},
                    "B1": {"group_id": "B"},
                },
            }
        ),
        encoding="utf-8",
    )
    workbooks: dict[str, dict[str, str]] = {}
    for subject in ("A1", "B1"):
        path = project_root / f"{subject}_C1.xlsx"
        path.write_bytes(b"fingerprint-only")
        workbooks[subject] = {"C1": str(path)}
    settings = normalize_dv_policy(
        {
            "harmonic_selection_profile": HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
            "group_significant_electrode_scope": GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN,
            "group_significant_selection_electrodes": ["O1", "O2"],
        }
    )
    request = build_group_harmonic_cache_request(
        project_root=project_root,
        subjects=["A1", "B1"],
        conditions=["C1"],
        subject_data=workbooks,
        base_frequency_hz=6.0,
        max_freq_hz=16.8,
        settings=settings,
        rois={"Posterior": ["O1"]},
    )
    changed_downstream_rois = build_group_harmonic_cache_request(
        project_root=project_root,
        subjects=["A1", "B1"],
        conditions=["C1"],
        subject_data=workbooks,
        base_frequency_hz=6.0,
        max_freq_hz=16.8,
        settings=settings,
        rois={"Different downstream ROI": ["FZ", "CZ"]},
    )

    assert request is not None
    assert changed_downstream_rois is not None
    assert changed_downstream_rois.cache_key == request.cache_key
    assert request.fingerprint["stats_settings"]["harmonic_selection_profile"] == (
        HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID
    )
    assert request.fingerprint["stats_settings"]["selection_electrodes"] == [
        "O1",
        "O2",
    ]
    assert request.fingerprint["selection_inputs"]["declared_group_ids"] == ["A", "B"]


def test_explicit_legacy_profile_keeps_unversioned_legacy_cache_identity(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    workbook = project_root / "S1_C1.xlsx"
    workbook.write_bytes(b"fingerprint-only")
    manifest_path = project_root / "project.json"
    manifest = {
        "schema_version": "2.1.0",
        "preprocessing": {},
        "event_map": {"C1": 1},
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    request_kwargs = {
        "project_root": project_root,
        "subjects": ["S1"],
        "conditions": ["C1"],
        "subject_data": {"S1": {"C1": str(workbook)}},
        "base_frequency_hz": 6.0,
        "max_freq_hz": 16.8,
        "settings": normalize_dv_policy(None),
        "rois": {"Posterior": ["O1"]},
    }
    unversioned = build_group_harmonic_cache_request(**request_kwargs)
    manifest["preprocessing"] = {
        "harmonic_selection_profile": HARMONIC_PROFILE_LEGACY_ID,
        "harmonic_selection_profile_version": "1.0",
        "fixed_harmonic_input_mode": "frequency_list",
        "fixed_harmonic_upper_harmonic_index": 0,
        "fixed_harmonic_upper_frequency_hz": 0.0,
        "group_significant_selection_electrodes": "",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    explicit = build_group_harmonic_cache_request(**request_kwargs)

    assert unversioned is not None
    assert explicit is not None
    assert explicit.cache_key == unversioned.cache_key


def _profile_workbooks(
    root: Path,
    subjects: list[str],
    conditions: list[str],
) -> dict[str, dict[str, str]]:
    subject_data: dict[str, dict[str, str]] = {}
    for subject in subjects:
        subject_data[subject] = {}
        for condition in conditions:
            path = root / f"{subject}_{condition}.xlsx"
            _write_profile_workbook(path)
            subject_data[subject][condition] = str(path)
    return subject_data


def _write_profile_workbook(
    path: Path,
    *,
    peak_harmonics: tuple[int, ...] = (1, 4),
) -> None:
    frequencies = np.arange(0.0, 10.5 + 1e-9, 0.3)
    amplitudes = 1.0 + 0.05 * np.sin(np.arange(len(frequencies), dtype=float))
    for peak_index, harmonic_index in enumerate(peak_harmonics):
        amplitudes[int(round((1.2 * harmonic_index) / 0.3))] = 10.0 - peak_index * 2.0
    frame = pd.DataFrame(
        [["O1", *amplitudes]],
        columns=["Electrode", *[f"{frequency:.4f}_Hz" for frequency in frequencies]],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="FullFFT Amplitude (uV)", index=False)
