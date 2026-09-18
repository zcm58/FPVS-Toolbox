from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import struct

import pandas as pd
import pytest

from Main_App.processing.provisional_harmonic_cache import ProvisionalHarmonicCache
from Tools.Stats.analysis.dv_policy_settings import DVPolicySettings


@pytest.fixture
def inputs(tmp_path):
    from Main_App.Shared.post_process_excel import write_results_workbook

    (tmp_path / "project.json").write_text(json.dumps({
        "participants": {"P1": {"group_id": "G1"}},
        "groups": {"G1": {"label": "Group one"}},
    }), encoding="utf-8")
    source = tmp_path / "P1_Faces_Results.fpvs"
    write_results_workbook(str(source), {
        "BCA (uV)": pd.DataFrame({"Electrode": ["O1"], "1.2000_Hz": [1.0]}),
    })
    return {
        "project_root": tmp_path,
        "subjects": ["P1"], "conditions": ["Faces"],
        "subject_data": {"P1": {"Faces": str(source)}},
        "rois": {"Occipital": ["O1"]},
        "settings": DVPolicySettings(),
        "log_func": lambda _message: None,
        "base_frequency_hz": 6.0, "oddball_frequency_hz": 1.2,
        "eligible_harmonic_orders": (1, 2, 3, 4),
        "spectral_eligibility_fingerprint": "domain-v1",
        "recording_assignments": None, "declared_session_ids": None,
        "participant_group_ids": None, "declared_group_ids": None,
        "electrode_exclusions_by_subject_condition": {},
        "expected_scalp_channels_by_subject_condition": {("p1", "faces"): ("O1",)},
    }


def _evidence():
    return (1.2, 2.4), {
        "rows": [{"z_score": 1.2345678901234567, "signed_zero": -0.0}],
        "tuple": (1.2, 2.4), "missing": float("nan"),
    }


def _bits(value):
    if isinstance(value, float):
        return struct.pack(">d", value)
    if isinstance(value, dict):
        return [(key, _bits(item)) for key, item in value.items()]
    if isinstance(value, (tuple, list)):
        return type(value), [_bits(item) for item in value]
    return value


def _counting_computation(calls):
    def compute(**kwargs):
        calls.append(kwargs)
        return _evidence()
    return compute


def test_exact_detached_evidence_reused_without_project_writes(inputs):
    cache = ProvisionalHarmonicCache()
    calls = []
    compute = _counting_computation(calls)
    before = {path: path.read_bytes() for path in inputs["project_root"].iterdir()}
    first = cache.resolve(compute, **inputs)
    first[1]["rows"][0]["z_score"] = 100.0
    changed_callback = {**inputs, "log_func": lambda _message: None}

    second = cache.resolve(compute, **changed_callback)

    assert len(calls) == 1
    assert _bits(second) == _bits(_evidence())
    second[1]["rows"].clear()
    assert _bits(cache.resolve(compute, **inputs)) == _bits(_evidence())
    assert {path: path.read_bytes() for path in inputs["project_root"].iterdir()} == before


@pytest.mark.parametrize("change", [
    {"subjects": ["P1", "P2"]},
    {"conditions": ["Faces", "Objects"]},
    {"rois": {"Occipital": ["O2"]}},
    {"base_frequency_hz": 7.0},
    {"oddball_frequency_hz": 1.0},
    {"eligible_harmonic_orders": (1, 2)},
    {"spectral_eligibility_fingerprint": "changed"},
    {"recording_assignments": {"P1": {"participant_id": "P1", "session_id": "Visit1"}}},
    {"declared_session_ids": ("Visit1", "Visit2")},
    {"participant_group_ids": {"P1": "G2"}},
    {"declared_group_ids": ("G1", "G2")},
    {"electrode_exclusions_by_subject_condition": {("p1", "faces"): frozenset({"O1"})}},
    {"expected_scalp_channels_by_subject_condition": {("p1", "faces"): ("O1", "O2")}},
])
def test_changed_scientific_inputs_recompute(inputs, change):
    cache = ProvisionalHarmonicCache()
    calls = []
    compute = _counting_computation(calls)
    cache.resolve(compute, **inputs)
    cache.resolve(compute, **{**inputs, **change})
    assert len(calls) == 2


def test_changed_selection_profile_recomputes(inputs):
    cache = ProvisionalHarmonicCache()
    calls = []
    compute = _counting_computation(calls)
    cache.resolve(compute, **inputs)
    changed = {**inputs, "settings": replace(inputs["settings"], group_significant_z_threshold=2.0)}
    cache.resolve(compute, **changed)
    assert len(calls) == 2


def test_retain_receipt_reuses_but_project_group_change_recomputes(inputs):
    cache = ProvisionalHarmonicCache()
    calls = []
    compute = _counting_computation(calls)
    cache.resolve(compute, **inputs)
    path = inputs["project_root"] / "project.json"
    manifest = json.loads(path.read_text())
    manifest["tools"] = {"frequency_domain_qc": {
        "review_complete": True, "last_review": {"at": "now"},
        "review_decisions": [{"decision": "retain"}],
    }}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    cache.resolve(compute, **inputs)
    assert len(calls) == 1
    manifest["participants"]["P1"]["group_id"] = "G2"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    cache.resolve(compute, **inputs)
    assert len(calls) == 2


def test_same_stat_source_byte_change_is_not_reused(inputs, monkeypatch):
    cache = ProvisionalHarmonicCache()
    calls = []
    compute = _counting_computation(calls)
    source = Path(inputs["subject_data"]["P1"]["Faces"])
    cache.resolve(compute, **inputs)
    original_stat = source.stat()
    old = source.read_bytes()
    modified = old.replace(b" ", b"\t", 1)
    assert len(modified) == len(old) and modified != old
    source.write_bytes(modified)
    real_stat = Path.stat
    monkeypatch.setattr(Path, "stat", lambda path, *args, **kwargs: (
        original_stat if path == source else real_stat(path, *args, **kwargs)
    ))

    cache.resolve(compute, **inputs)

    assert len(calls) == 2


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_invalid_companion_falls_back_to_current_computation(inputs, damage):
    cache = ProvisionalHarmonicCache()
    source = Path(inputs["subject_data"]["P1"]["Faces"])
    descriptor = json.loads(source.read_text())["condition_companion"]
    companion = source.with_name(descriptor["path"])
    cache.resolve(lambda **kwargs: _evidence(), **inputs)
    if damage == "changed":
        data = bytearray(companion.read_bytes())
        data[len(data) // 2] ^= 1
        companion.write_bytes(data)
    else:
        companion.unlink()

    def read_current_source(**kwargs):
        from Main_App.io import read_xlsx_sheet_selected_columns
        read_xlsx_sheet_selected_columns(
            source, sheet_name="BCA (uV)", required_columns=["Electrode", "1.2000_Hz"],
        )
        return _evidence()

    with pytest.raises((OSError, ValueError)):
        cache.resolve(read_current_source, **inputs)


def test_changed_source_during_computation_is_not_published(inputs):
    cache = ProvisionalHarmonicCache()
    calls = []
    source = Path(inputs["subject_data"]["P1"]["Faces"])

    def compute(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            source.write_text(source.read_text() + "\n", encoding="utf-8")
        return _evidence()

    cache.resolve(compute, **inputs)
    cache.resolve(compute, **inputs)
    assert len(calls) == 2


def test_bounded_entries_clear_and_inflight_completion(inputs):
    cache = ProvisionalHarmonicCache()
    calls = []
    compute = _counting_computation(calls)
    for rate in (1.0, 1.1, 1.2):
        cache.resolve(compute, **{**inputs, "oddball_frequency_hz": rate})
    assert len(cache._entries) == 2
    cache.resolve(compute, **{**inputs, "oddball_frequency_hz": 1.0})
    assert len(calls) == 4
    cache.clear()
    assert len(cache._entries) == 0

    def interrupted(**kwargs):
        cache.clear()
        return _evidence()

    cache.resolve(interrupted, **inputs)
    assert len(cache._entries) == 0


def test_corrupt_private_entry_cannot_change_returned_evidence(inputs):
    cache = ProvisionalHarmonicCache()
    calls = []
    compute = _counting_computation(calls)
    cache.resolve(compute, **inputs)
    key = next(iter(cache._entries))
    cache._entries[key][1][1]["rows"] = [{"z_score": 999.0}]
    result = cache.resolve(compute, **inputs)
    assert len(calls) == 2
    assert _bits(result) == _bits(_evidence())


def test_failed_computation_is_not_cached(inputs):
    cache = ProvisionalHarmonicCache()
    def fail(**kwargs):
        raise RuntimeError("Current harmonic selection failed")
    with pytest.raises(RuntimeError, match="Current harmonic selection failed"):
        cache.resolve(fail, **deepcopy(inputs))
    assert len(cache._entries) == 0


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("profile", [
    "legacy_fpvs_toolbox", "significant_only_exploratory",
    "dzhelyova_poncet_two_consecutive_failures",
])
def test_real_adaptive_selection_reuses_every_metadata_bit(inputs, native, profile):
    import numpy as np
    from Main_App.Shared.post_process_excel import write_results_workbook
    from Main_App.processing.frequency_domain_qc import _provisional_harmonics
    from Tools.Stats.analysis.dv_policy_settings import normalize_dv_policy

    frequencies = np.arange(0.0, 10.5 + 1e-9, 0.1)
    values = 1.0 + 0.05 * np.sin(np.arange(len(frequencies), dtype=float))
    values[12] = 10.0
    values[48] = 8.0
    frame = pd.DataFrame(
        [["O1", *values]],
        columns=["Electrode", *[f"{value:.4f}_Hz" for value in frequencies]],
    )
    source = inputs["project_root"] / ("adaptive.fpvs" if native else "adaptive.xlsx")
    if native:
        write_results_workbook(str(source), {"FullFFT Amplitude (uV)": frame})
    else:
        with pd.ExcelWriter(source, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="FullFFT Amplitude (uV)", index=False)
    inputs = {
        **inputs, "subject_data": {"P1": {"Faces": str(source)}},
        "settings": normalize_dv_policy({"harmonic_selection_profile": profile}),
        "participant_group_ids": {"P1": "G1"}, "declared_group_ids": ("G1",),
    }
    cache = ProvisionalHarmonicCache()
    calls = []

    def compute(**kwargs):
        calls.append(kwargs)
        return _provisional_harmonics(**kwargs)

    calculated = cache.resolve(compute, **inputs)
    cached = cache.resolve(compute, **inputs)

    assert len(calls) == 1
    assert _bits(cached) == _bits(calculated)
    assert cached[1]["selection_fingerprint"] == calculated[1]["selection_fingerprint"]
