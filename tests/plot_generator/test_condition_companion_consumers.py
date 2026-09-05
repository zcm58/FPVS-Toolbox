"""Saved compact metrics and eligibility work across their active consumers."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from Main_App.io.condition_data import (
    ConditionDataError,
    condition_manifest_frame,
    write_condition_companion,
)
from Tools.Plot_Generator.source_identity import (
    SNRPublicationError,
    capture_stable_source_identity,
    capture_stable_source_snapshot,
    verify_source_snapshot_after_read,
)
from Tools.Publication_Maps.metrics import (
    _capture_workbook_identity,
    verify_publication_workbooks_unchanged,
)
from Tools.Publication_Maps.models import PublicationMapInputError, WorkbookEntry
from Tools.Publication_Maps.xlsx_metric_reader import read_metric_sheet_selected_columns
from Tools.Ratio_Calculator.compute import read_participant_file
from Tools.Stats.io.excel_io import safe_read_excel


def _write_compact(path: Path):
    frames = {
        name: pd.DataFrame({
            "Electrode": ["Cz", "Pz"],
            "1.2000_Hz": [scale * 0.12345678901234568, scale * -0.875],
            "2.4000_Hz": [scale * 1.125, np.nan],
        })
        for scale, name in enumerate(("SNR", "Z Score", "BCA (uV)"), start=1)
    }
    descriptor = write_condition_companion(path, frames)
    with pd.ExcelWriter(path) as writer:
        condition_manifest_frame(descriptor).to_excel(
            writer, sheet_name="Condition Data", index=False,
        )
    return descriptor, frames


def test_all_compact_metric_readers_preserve_saved_values_without_excel_copies(
    tmp_path, monkeypatch,
):
    workbook = tmp_path / "P01.xlsx"
    _descriptor, frames = _write_compact(workbook)

    def no_excel_values(*_args, **_kwargs):
        raise AssertionError("Compact values must not be read through pandas Excel")

    monkeypatch.setattr(pd, "read_excel", no_excel_values)
    snr, z, bca, columns = read_participant_file(workbook)
    assert columns == ["1.2000_Hz", "2.4000_Hz"]
    for name, actual in (("SNR", snr), ("Z Score", z), ("BCA (uV)", bca)):
        pd.testing.assert_frame_equal(actual, frames[name], check_exact=True)
        scalp = read_metric_sheet_selected_columns(
            workbook, sheet_name=name,
            required_columns=["Electrode", "1.2000_Hz", "9.6000_Hz"],
        )
        pd.testing.assert_frame_equal(
            scalp, frames[name].loc[:, ["Electrode", "1.2000_Hz"]], check_exact=True,
        )
        stats = safe_read_excel(workbook, sheet_name=name, index_col="Electrode")
        pd.testing.assert_frame_equal(stats, frames[name].set_index("Electrode"), check_exact=True)


@pytest.mark.parametrize("damage", ["missing", "tampered"])
def test_cached_compact_values_and_publication_identities_reject_damaged_companion(
    tmp_path, damage,
):
    workbook = tmp_path / "P01.xlsx"
    descriptor, _frames = _write_compact(workbook)
    safe_read_excel(workbook, sheet_name="BCA (uV)")
    snapshot = capture_stable_source_snapshot(workbook)
    scalp_entry = _capture_workbook_identity(
        WorkbookEntry(condition="Faces", subject_id="P01", path=workbook),
        cancel_check=None,
    )
    assert snapshot.identity.condition_companion == descriptor
    assert capture_stable_source_identity(workbook) == snapshot.identity
    assert scalp_entry.condition_companion == descriptor
    companion = workbook.with_name(descriptor["path"])
    if damage == "missing":
        companion.unlink()
    else:
        data = bytearray(companion.read_bytes())
        data[-1] ^= 1
        companion.write_bytes(data)
    with pytest.raises(ConditionDataError, match="[Cc]ompanion"):
        safe_read_excel(workbook, sheet_name="BCA (uV)")
    with pytest.raises(ValueError, match="[Cc]ompanion"):
        read_participant_file(workbook)
    with pytest.raises(SNRPublicationError, match="[Cc]ompanion"):
        verify_source_snapshot_after_read(workbook, snapshot=snapshot)
    with pytest.raises(PublicationMapInputError, match="[Cc]ompanion"):
        verify_publication_workbooks_unchanged((scalp_entry,))


def test_stats_cache_fingerprints_bind_compact_values(tmp_path):
    from Tools.Stats.analysis.dv_policies import _source_workbook_identities
    from Tools.Stats.analysis.dv_policy_fixed_predefined import _fixed_source_workbook_fingerprints
    from Tools.Stats.analysis.dv_policy_group_significant import (
        _selection_source_workbook_fingerprints,
        _workbook_signature,
    )
    from Tools.Stats.data.group_harmonic_cache import _workbook_fingerprint

    workbook = tmp_path / "P01.xlsx"
    descriptor, _frames = _write_compact(workbook)
    shared = dict(subjects=["P01"], conditions=["Faces"], subject_data={"P01": {"Faces": str(workbook)}})
    one = dict(subject="P01", condition="Faces", file_path=str(workbook))
    assert json.loads(_source_workbook_identities(**shared)[0][-1]) == descriptor
    assert json.loads(_workbook_signature(**one).condition_companion_json) == descriptor
    assert _fixed_source_workbook_fingerprints(**shared, project_root=tmp_path)[0]["condition_companion"] == descriptor
    assert _selection_source_workbook_fingerprints(**shared, cache_request=None)[0]["condition_companion"] == descriptor
    assert _workbook_fingerprint(tmp_path, **one).to_manifest()["condition_companion"] == descriptor
