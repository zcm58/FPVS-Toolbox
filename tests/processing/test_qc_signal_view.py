from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import struct
import zipfile

import numpy as np
import pytest

from Main_App.processing.qc_signal_view import (
    QcSignalViewRequest, _read_view, envelope_from_reader, load_qc_signal_view,
    peak_preserving_values, request_from_source,
    source_content_identity,
)


def test_peak_preview_retains_single_sample_impulses_between_old_stride_points():
    data = np.zeros(50000)
    data[73], data[11111] = 900.0, -400.0
    preview = peak_preserving_values(data)
    assert max(preview) == 900.0
    assert min(preview) == -400.0
    assert len(preview) <= 256
    assert peak_preserving_values(np.array([])) == ()
    assert peak_preserving_values(np.array([np.nan, np.inf])) == (None, None)


def test_envelope_keeps_extrema_and_exact_time_with_bounded_sequential_reads():
    samples = np.zeros((2, 500000))
    samples[0, 123456], samples[1, 411111] = 12e-6, -30e-6
    reads = []

    def read(start, stop):
        reads.append((start, stop))
        return samples[:, start:stop]

    times, traces = envelope_from_reader(read, start=100, stop=490000, sfreq=1000,
                                          names=("Fp1", "Fp2"), bins=400)
    assert max(traces[0].maximum_uv) == 12
    assert min(traces[1].minimum_uv) == -30
    assert 0.1 <= times[0] < times[-1] < 490
    assert max(stop - start for start, stop in reads) <= 131072
    assert len(reads) == 4
    assert all(left[1] == right[0] for left, right in zip(reads[:-1], reads[1:], strict=True))


def test_envelope_cancellation_and_nonfinite_gaps():
    with pytest.raises(InterruptedError):
        envelope_from_reader(lambda *_: None, start=0, stop=10, sfreq=1,
                             names=("Fp1",), should_cancel=lambda: True)
    _, traces = envelope_from_reader(lambda start, stop: np.full((1, stop - start), np.nan),
                                    start=0, stop=10, sfreq=1, names=("Fp1",))
    assert all(value is None for value in traces[0].minimum_uv)


def _source_view(tmp_path, *, mode="initial_reference"):
    names = ["Fp1", "Fp2", "AF3", "AF4", "EXG1", "EXG2", "Status"]
    samples = np.tile(np.arange(1000) * 1e-6, (len(names), 1))
    samples[4] = 10e-6
    samples[5] = 4e-6
    samples[0, 755] = 1500e-6
    positions = {name: [0.01 * (i + 1), 0.04, 0.08] for i, name in enumerate(names[:4])}
    request = replace(request_from_source(tmp_path / "source.bdf", tmp_path, {}, channel="Fp1",
                                         spans=((1.0, 2.0), (7.0, 9.0))),
                      mode=mode, occurrence_index=1, duration_seconds=1)
    reads = []

    def reader(picks, start, stop):
        reads.append((start, stop))
        return samples[picks, start:stop]

    def view(current_request):
        return _read_view(current_request, reader, names, 100, 1000, positions,
                          ("EXG1", "EXG2"), None, source_signature=("test",))

    return request, view, reads


def test_occurrences_stay_separate_and_reference_math_remains_in_physical_units(tmp_path):
    request, view, reads = _source_view(tmp_path, mode="reference_comparison")
    result = view(request)
    assert result.start_seconds == 7.0
    assert result.stop_seconds == 8.0
    assert min(start for start, _stop in reads) >= 700
    assert max(stop for _start, stop in reads) <= 900
    assert max(result.traces[0].maximum_uv) == pytest.approx(1500)
    assert max(result.traces[1].maximum_uv) == pytest.approx(1493)
    assert result.traces[2].minimum_uv[0] == pytest.approx(10)
    assert result.traces[3].minimum_uv[0] == pytest.approx(4)
    assert result.traces[4].minimum_uv[0] == pytest.approx(6)


def test_panning_reuses_only_matching_overview_and_never_rereads_full_occurrence(tmp_path):
    request, view, reads = _source_view(tmp_path)
    first = view(request)
    reads.clear()
    second = view(replace(request, overview_cache=first.overview_cache, start_seconds=8))
    assert second.overview is first.overview
    assert reads == [(800, 900)]
    reads.clear()
    view(replace(request, overview_cache=first.overview_cache, mode="raw"))
    assert reads[0] == (700, 900)


def test_request_omits_all_project_and_cache_state_except_loader_settings(tmp_path):
    class NeverCopy:
        def __deepcopy__(self, _memo):
            raise AssertionError("Large scientific state should not be copied on the GUI thread")

    request = request_from_source(tmp_path / "x.bdf", tmp_path,
                                  {"event_plans": NeverCopy(), "max_idx_keep": 32, "ref_chan1": "EXG3"})
    assert request.params == {"max_idx_keep": 32, "ref_chan1": "EXG3"}


def test_reference_finding_opens_pair_comparison_and_missing_scalp_never_substitutes(tmp_path):
    request = request_from_source(tmp_path / "source.bdf", tmp_path, {"ref_ch1": "EXG3"}, channel="exg3")
    assert request.mode == "reference_comparison"
    assert request.channel == ""
    request, view, _reads = _source_view(tmp_path)
    with pytest.raises(ValueError, match="retained selection"):
        view(replace(request, channel="Oz"))


def test_miniature_preserves_occurrence_gaps_and_leaves_scoring_samples_untouched():
    from Main_App.processing.preprocess import _kurtosis_signal_preview

    samples = np.array([[0.0, 8e-6, 0.0, 0.0, 0.0, -9e-6, 0.0, 0.0]])
    original = samples.copy()
    plan = {"unique_relative_spans": [[100, 104], [200, 204]], "spans": [
        {"target_coordinates": {"start_relative_sample": 100, "stop_relative_sample": 104}},
        {"target_coordinates": {"start_relative_sample": 200, "stop_relative_sample": 204}},
    ]}
    preview = _kurtosis_signal_preview(samples, ["Fp1"], ("Fp1",),
                                       params={"_fpvs_realized_analysis_span_plan": plan})
    values = preview["channels"]["Fp1"]
    separator = values.index(None)
    assert max(values[:separator]) == 8
    assert min(values[separator + 1:]) == -9
    assert np.array_equal(samples, original)


def test_lazy_source_honors_channel_limit_and_original_recording_clock(tmp_path, monkeypatch):
    from Main_App.io import load_utils
    from Main_App.processing import qc_review_diagnostics

    source = tmp_path / "source.bdf"
    source.write_bytes(b"source")
    names = ["Fp1", "Fp2", "EXG1", "EXG2", "Trigger"]
    samples = np.zeros((5, 100))
    captured = {}

    def get_data(*, picks, start, stop):
        indices = [names.index(name) if isinstance(name, str) else name for name in picks]
        return samples[indices, start:stop]

    raw = SimpleNamespace(ch_names=names, n_times=100, first_samp=300, get_data=get_data,
                          info={"sfreq": 10, "chs": [{"loc": [0.01 * i, 0.02, 0.09]} for i in range(5)]})

    @contextmanager
    def open_raw(_host, _path, **kwargs):
        captured.update(kwargs)
        yield raw
        captured["closed"] = True

    def diagnostics(_data, **kwargs):
        captured["diagnostic_coordinates"] = (kwargs["sample_offset"], kwargs["source_first_samp"])
        return {"evaluation_scope": kwargs["evaluation_scope"]}

    monkeypatch.setattr(load_utils, "open_preflight_eeg_file", open_raw)
    monkeypatch.setattr(qc_review_diagnostics, "build_qc_review_diagnostics", diagnostics)
    result = load_qc_signal_view(request_from_source(source, tmp_path, {"max_idx_keep": "2", "stim": "Trigger"},
                                                     channel="Fp1", spans=((8, 9),)))
    assert captured["first_n_channels"] == 2
    assert captured["stim_channel"] == "Trigger"
    assert "Trigger" not in result.available_channels
    assert captured["closed"]
    assert captured["diagnostic_coordinates"] == (380, 300)
    assert result.start_seconds == 8
    assert result.stop_seconds == 9


def _prepared_request(tmp_path):
    source = tmp_path / "source.bdf"
    source.write_bytes(b"synthetic source identity")
    folder = tmp_path / ".fpvs_cache" / "prepared_kurtosis" / "test"
    folder.mkdir(parents=True)
    path = folder / "test.npz"
    data = np.zeros((2, 1000))
    data[0, 779] = 33e-6
    np.savez(path, samples=data, metadata_json=np.asarray(json.dumps({"key": "test", "evidence_fingerprint": "fp"})))
    stat = source.stat()
    descriptor = {"path": str(path), "source_stat": [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns],
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "key": "test",
                  "evidence_fingerprint": "fp", "channels": ["Fp1", "Fp2"], "sfreq": 100,
                  "n_times": 1000, "positions": {}}
    return QcSignalViewRequest(source, tmp_path, {}, channel="Fp1", spans=((7, 8),),
                               prepared=descriptor, mode="prepared", duration_seconds=1)


def test_prepared_view_reads_float64_checkpoint_without_loading_recording_in_ram(tmp_path):
    request = _prepared_request(tmp_path)
    result = load_qc_signal_view(request)
    assert max(result.overview.maximum_uv) == 33
    assert result.start_seconds == 7
    assert result.stop_seconds == 8
    assert result.verified_checkpoint
    # The result owns small tuples only; Windows can release/delete the artifact.
    Path(request.prepared["path"]).unlink()


def _rewrite_checkpoint_sample_with_restored_timestamp(path):
    before = path.stat()
    with zipfile.ZipFile(path) as archive:
        member = archive.getinfo("samples.npy")
    with path.open("r+b") as stream:
        stream.seek(member.header_offset)
        header = stream.read(30)
        name_length, extra_length = struct.unpack_from("<HH", header, 26)
        stream.seek(member.header_offset + 30 + name_length + extra_length)
        np.lib.format.read_magic(stream)
        np.lib.format.read_array_header_1_0(stream)
        stream.seek(779 * 8, 1)
        stream.write(struct.pack("<d", 66e-6))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns


def test_same_size_restored_timestamp_checkpoint_edit_never_reuses_old_overview(tmp_path):
    request = _prepared_request(tmp_path)
    first = load_qc_signal_view(request)
    _rewrite_checkpoint_sample_with_restored_timestamp(Path(request.prepared["path"]))
    with pytest.raises(ValueError, match="integrity"):
        load_qc_signal_view(replace(request, verified_checkpoint=first.verified_checkpoint,
                                    overview_cache=first.overview_cache))


@pytest.mark.parametrize("interruption", ["mutated", "cancelled"])
def test_checkpoint_integrity_rechecked_after_read_and_mapping_released(tmp_path, monkeypatch, interruption):
    from Main_App.processing import qc_signal_view

    request = _prepared_request(tmp_path)
    path = Path(request.prepared["path"])
    read_view = qc_signal_view._read_view
    cancelled = False

    def during_read(*args, **kwargs):
        nonlocal cancelled
        if interruption == "mutated":
            _rewrite_checkpoint_sample_with_restored_timestamp(path)
        result = read_view(*args, **kwargs)
        cancelled = interruption == "cancelled"
        return result

    monkeypatch.setattr(qc_signal_view, "_read_view", during_read)
    with pytest.raises(ValueError if interruption == "mutated" else InterruptedError):
        load_qc_signal_view(request, should_cancel=lambda: cancelled)
    path.unlink()


def test_full_scan_diagnostics_without_checkpoint_reject_same_size_source_edit(tmp_path):
    source = tmp_path / "source.bdf"
    source.write_bytes(b"original source")
    identity = source_content_identity(source)
    before = source.stat()
    request = replace(request_from_source(source, tmp_path, {}),
                      diagnostics={"source_identity": identity, "evaluation_scope": "all_analyzed_occurrences"})
    source.write_bytes(b"modified source")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_size == before.st_size
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    with pytest.raises(ValueError, match="content changed"):
        load_qc_signal_view(request)


def test_unbound_raw_view_recomputes_overview_after_restored_timestamp_source_edit(tmp_path, monkeypatch):
    from Main_App.io import load_utils
    from Main_App.processing import qc_review_diagnostics

    source = tmp_path / "source.bdf"
    source.write_bytes(b"33")
    names = ["Fp1", "EXG1", "EXG2"]

    @contextmanager
    def open_raw(*_args, **_kwargs):
        amplitude = int(source.read_bytes()) * 1e-6
        samples = np.zeros((3, 100))
        samples[0, 33] = amplitude
        yield SimpleNamespace(
            ch_names=names, n_times=100, first_samp=0,
            info={"sfreq": 100, "chs": [{"loc": [0.01, 0.02, 0.09]}] * 3},
            get_data=lambda *, picks, start, stop: samples[
                [names.index(name) if isinstance(name, str) else name for name in picks], start:stop],
        )

    monkeypatch.setattr(load_utils, "open_preflight_eeg_file", open_raw)
    monkeypatch.setattr(qc_review_diagnostics, "build_qc_review_diagnostics", lambda *_args, **_kwargs: {})
    request = replace(request_from_source(source, tmp_path, {}, channel="Fp1"), mode="raw")
    first = load_qc_signal_view(request)
    before = source.stat()
    source.write_bytes(b"66")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    second = load_qc_signal_view(replace(request, overview_cache=first.overview_cache))
    assert max(first.overview.maximum_uv) == pytest.approx(33)
    assert max(second.overview.maximum_uv) == pytest.approx(66)
    assert max(second.traces[0].maximum_uv) == pytest.approx(66)


@pytest.mark.parametrize("problem", ["corrupt", "changed_source", "outside_project", "wrong_evidence"])
def test_prepared_view_rejects_invalid_or_changed_evidence(tmp_path, problem):
    request = _prepared_request(tmp_path)
    if problem == "corrupt":
        with Path(request.prepared["path"]).open("ab") as stream:
            stream.write(b"changed")
    elif problem == "changed_source":
        request.path.write_bytes(b"replacement source")
    elif problem == "outside_project":
        request = replace(request, project_root=tmp_path / "other")
    else:
        request = replace(request, prepared={**request.prepared, "evidence_fingerprint": "changed"})
    with pytest.raises(ValueError):
        load_qc_signal_view(request)
