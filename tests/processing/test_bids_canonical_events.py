"""Published native marker evidence cannot be rounded or silently corrupted."""

from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import mne
import numpy as np
import pytest

from Main_App.io.bids_import import IMPORT_VERSION, _restore_import_events, _valid_publication
from Main_App.io.pipeline_events import snapshot_canonical_event_metadata
from Main_App.io.recording_events import RecordingEventError


def _case():
    raw = mne.io.RawArray(
        np.zeros((2, 20)), mne.create_info(["E1", "Status"], 250, ["eeg", "stim"]),
        verbose=False,
    )
    raw._fpvs_canonical_events = np.array([[0, 0, 3], [1, 0, 3], [10, 0, 55]], dtype=np.int64)
    raw._fpvs_canonical_events_sfreq = 250.0
    frame = snapshot_canonical_event_metadata(raw, cache_key="import-key")
    metadata = {
        "canonical_events": frame["events"], "canonical_events_sfreq": frame["sfreq"],
        "canonical_events_first_samp": frame["first_samp"],
        "canonical_events_schema_version": frame["schema_version"],
        "canonical_events_sha256": frame["sha256"], "sfreq": 250.0, "n_times": 20,
        "mobile_import": {"event_policy": {"authority": "status"}},
        "subject_info": None, "digitization": None, "bvrf_header": None, "bvrf_marker_rows": None,
    }
    return raw, metadata


def _resign(metadata):
    frame = {
        "schema_version": metadata["canonical_events_schema_version"],
        "sfreq": metadata["canonical_events_sfreq"],
        "first_samp": metadata["canonical_events_first_samp"],
        "n_times": metadata["n_times"], "events": metadata["canonical_events"],
    }
    metadata["canonical_events_sha256"] = hashlib.sha256(json.dumps(
        {"cache_key": "import-key", "markers": frame}, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def test_import_evidence_roundtrip_keeps_first_and_repeated_markers():
    raw, metadata = _case()
    np.testing.assert_array_equal(
        _restore_import_events(raw, json.loads(json.dumps(metadata)), import_key="import-key"),
        [[0, 0, 3], [1, 0, 3], [10, 0, 55]],
    )


@pytest.mark.parametrize("change", [
    "fractional_sample", "fractional_code", "outside_grid", "wrong_shape", "empty_rows",
    "missing_checksum", "missing_events", "stale_rate", "changed_code",
])
def test_corrupt_import_evidence_rejects_read_and_cache_reuse(tmp_path, change):
    raw, metadata = _case()
    if change == "fractional_sample":
        metadata["canonical_events"][1][0] = 1.5
    elif change == "fractional_code":
        metadata["canonical_events"][1][2] = 3.5
    elif change == "outside_grid":
        metadata["canonical_events"][2][0] = 20
    elif change == "wrong_shape":
        metadata["canonical_events"] = [0, 0, 3]
    elif change == "empty_rows":
        metadata["canonical_events"] = [[], [], []]
    elif change == "missing_checksum":
        metadata.pop("canonical_events_sha256")
    elif change == "missing_events":
        metadata.pop("canonical_events")
    elif change == "stale_rate":
        metadata["canonical_events_sfreq"] = 125.0
    else:
        metadata["canonical_events"][1][2] = 99
    # Exercise semantic validation independently of the corruption checksum.
    if change in {"fractional_sample", "fractional_code", "outside_grid", "wrong_shape", "empty_rows", "stale_rate"}:
        _resign(metadata)
    with pytest.raises((RecordingEventError, KeyError, ValueError)):
        _restore_import_events(raw, metadata, import_key="import-key")
    manifest = {"version": IMPORT_VERSION, "key": "import-key", "source_identity": [],
                "recording": metadata, "outputs": []}
    (tmp_path / "import.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert _valid_publication(tmp_path, (), "import-key") is None


def test_empty_import_event_authority_is_valid_and_detached():
    raw, metadata = _case()
    metadata["canonical_events"] = []
    _resign(metadata)
    probe = SimpleNamespace(info=raw.info, first_samp=0, n_times=20)
    assert _restore_import_events(probe, deepcopy(metadata), import_key="import-key").shape == (0, 3)
