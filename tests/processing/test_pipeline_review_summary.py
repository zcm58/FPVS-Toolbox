"""Describe native QC evidence using exact floats without making decisions."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import struct


SCRIPT = Path(__file__).parents[2] / "scripts/manual_diagnostics/pipeline_review_summary.py"
SPEC = importlib.util.spec_from_file_location("pipeline_review_summary_test", SCRIPT)
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


def test_review_summary_separates_native_strict_extreme_policy_and_actual_manual_rows(tmp_path):
    from Main_App.processing.kurtosis_qc import KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD

    def item(channel, score):
        return {"path": str(tmp_path / "copied.bdf"), "participant_id": "P1", "recording_id": "P1",
                "session_id": None, "session_label": None, "channel": channel,
                "evidence": {"fingerprint": "a" * 64, "channels": [{"channel": channel, "validity": "valid",
                    "exceeds_threshold": True, "signed_z": {"float64_bits": struct.pack(">d", score).hex(), "display": repr(score)}}]}}
    receipt = {"recordings": ["P1"], "kurtosis_review": {"cancelled": False,
        "results": [{"recording_id": "P1", "error": None, "review_items": [item("FP1", KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD + 1),
            item("FP2", KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD), item("CZ", -KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD)]}]}}
    project = {"preprocessing": {"kurtosis_auto_interpolate_all": False, "kurtosis_review_decisions_by_recording": {}},
               "experimental_qc": {"kurtosis_review_auto_interpolate_extreme": True}}
    original_receipt, original_project = deepcopy(receipt), deepcopy(project)
    report = summary.describe_kurtosis(receipt, project)
    assert report["findings_count"] == 3
    assert report["disposition_counts"] == {"automatic_extreme": 1, "manual_new": 2}
    assert report["actual_manual_review_count"] == 2
    assert report["recordings_requiring_actual_manual_review"] == ["P1"]
    assert receipt == original_receipt
    assert project == original_project


def test_exact_negative_zero_float_restore():
    value = summary.restore_float_bits({"float64_bits": "8000000000000000", "display": "-0.0"})
    assert struct.pack(">d", value).hex() == "8000000000000000"
