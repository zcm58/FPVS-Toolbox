from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import mne
import numpy as np

from Main_App.Shared.fft_crop_utils import CropResult
from Main_App.workers import process_runner


def test_run_full_pipeline_uses_single_epoch_contract_per_label(monkeypatch, tmp_path: Path) -> None:
    info = mne.create_info(["Cz", "Pz", "Status"], sfreq=8.0, ch_types=["eeg", "eeg", "stim"])
    raw = mne.io.RawArray(np.zeros((3, 64), dtype=float), info, verbose=False)
    events = np.asarray([[8, 0, 21], [32, 0, 21]], dtype=int)
    crop_results = {
        (21, 0): CropResult(
            crop_start_sample=8,
            n_samples=4,
            n55_raw=2,
            n55_dedup=2,
            cycles=1,
            block_start_sample=8,
            block_end_sample=24,
            first55_sample=8,
            last55_sample=12,
            available_samples=4,
            fallback=False,
        ),
        (21, 1): CropResult(
            crop_start_sample=32,
            n_samples=4,
            n55_raw=2,
            n55_dedup=2,
            cycles=1,
            block_start_sample=32,
            block_end_sample=48,
            first55_sample=32,
            last55_sample=36,
            available_samples=4,
            fallback=False,
        ),
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "begin_preproc_audit",
        lambda *_args, **_kwargs: {"file": "fake.bdf"},
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "perform_preprocessing",
        lambda raw_input, params, log_func, filename_for_log: (raw_input, 0),
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "finalize_preproc_audit",
        lambda *args, **kwargs: ({"n_rejected": 0}, []),
    )
    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        lambda _app, _filepath, ref_pair=None, first_n_channels=None: raw.copy(),
    )
    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.LegacyCtx",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    def _capture_post_export(ctx, _labels):
        captured["epochs_dict"] = ctx.preprocessed_data
        ctx.export_timing_records.append(
            {"source": "post_process", "stage": "workbook_write", "elapsed_ms": 7}
        )
        return 1

    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.run_post_export",
        _capture_post_export,
    )
    monkeypatch.setattr(process_runner, "compute_fft_crop_from_events", lambda **_kwargs: (crop_results, 4, []))
    monkeypatch.setattr(
        process_runner,
        "compute_onbin_step",
        lambda fs, f_oddball=process_runner.ODDBALL_FREQ: (int(fs), 4, None),
    )
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events)

    fake_bdf = tmp_path / "fake.bdf"
    fake_bdf.write_bytes(b"fake bdf")

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "epoch_start": 0.0,
            "epoch_end": 1.0,
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
        },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "ok"
    assert "epochs_dict" in captured
    epochs = captured["epochs_dict"]["A"][0]
    assert epochs.get_data().shape == (2, 3, 4)
    assert epochs.metadata["crop_mode"].tolist() == ["55_onbin", "55_onbin"]
    assert epochs.metadata["N_step"].tolist() == [4, 4]
    assert epochs.metadata["N_mod_step"].tolist() == [0, 0]
    assert epochs.metadata["fallback_reason"].tolist() == ["", ""]
    assert result["preproc_cache_status"] == "disabled"
    assert "events" in result["timings_ms"]
    assert "epochs" in result["timings_ms"]
    assert result["export_timing_records"] == [
        {"source": "post_process", "stage": "workbook_write", "elapsed_ms": 7}
    ]


def test_run_full_pipeline_hard_fails_when_locked_fft_crop_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    info = mne.create_info(["Cz", "Pz", "Status"], sfreq=8.0, ch_types=["eeg", "eeg", "stim"])
    raw = mne.io.RawArray(np.zeros((3, 64), dtype=float), info, verbose=False)
    events = np.asarray([[8, 0, 21], [32, 0, 21]], dtype=int)
    crop_results = {
        (21, 0): CropResult(
            crop_start_sample=8,
            n_samples=4,
            n55_raw=2,
            n55_dedup=2,
            cycles=1,
            block_start_sample=8,
            block_end_sample=24,
            first55_sample=8,
            last55_sample=12,
            available_samples=4,
            fallback=False,
        ),
        (21, 1): CropResult(
            crop_start_sample=32,
            n_samples=0,
            n55_raw=0,
            n55_dedup=0,
            cycles=0,
            block_start_sample=32,
            block_end_sample=48,
            available_samples=0,
            fallback=True,
            fallback_reason="insufficient_55",
        ),
    }
    post_export_calls: list[str] = []

    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "begin_preproc_audit",
        lambda *_args, **_kwargs: {"file": "fake.bdf"},
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "perform_preprocessing",
        lambda raw_input, params, log_func, filename_for_log: (raw_input, 0),
    )
    monkeypatch.setattr(
        process_runner.backend_preprocess,
        "finalize_preproc_audit",
        lambda *args, **kwargs: ({"n_rejected": 0}, []),
    )
    monkeypatch.setattr(
        "Main_App.io.load_utils.load_eeg_file",
        lambda _app, _filepath, ref_pair=None, first_n_channels=None: raw.copy(),
    )
    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.LegacyCtx",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    def _unexpected_post_export(_ctx, _labels):
        post_export_calls.append("called")
        return 1

    monkeypatch.setattr(
        "Main_App.exports.post_export_adapter.run_post_export",
        _unexpected_post_export,
    )
    monkeypatch.setattr(process_runner, "compute_fft_crop_from_events", lambda **_kwargs: (crop_results, 4, []))
    monkeypatch.setattr(
        process_runner,
        "compute_onbin_step",
        lambda fs, f_oddball=process_runner.ODDBALL_FREQ: (int(fs), 4, None),
    )
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: events)

    fake_bdf = tmp_path / "fake.bdf"
    fake_bdf.write_bytes(b"fake bdf")

    result = process_runner._run_full_pipeline_for_file(
        file_path=fake_bdf,
        settings={
            "stim_channel": "Status",
            "epoch_start": 0.0,
            "epoch_end": 1.0,
            "ref_channel1": "EXG1",
            "ref_channel2": "EXG2",
            "enable_preprocessed_cache": False,
        },
        event_map={"A": 21},
        save_folder=tmp_path / "out",
        project_root=tmp_path / "project",
    )

    assert result["status"] == "error"
    assert result["stage"] == "epochs"
    assert "Locked FFT crop required" in str(result["error"])
    assert "Fixed-epoch fallback is disabled" in str(result["error"])
    assert post_export_calls == []


def test_preprocessed_cache_round_trip_preserves_audit_metadata(tmp_path: Path) -> None:
    info = mne.create_info(["Cz", "Status"], sfreq=8.0, ch_types=["eeg", "stim"])
    raw = mne.io.RawArray(np.zeros((2, 16), dtype=float), info, verbose=False)
    fake_bdf = tmp_path / "fake.bdf"
    fake_bdf.write_bytes(b"raw source")
    settings = {
        "stim_channel": "Status",
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "downsample_rate": 8,
        "enable_preprocessed_cache": True,
    }
    audit_before = {"file": "fake.bdf", "ch_names": ["Cz", "EXG1", "EXG2", "Status"]}
    payload = process_runner._preproc_cache_payload(
        fake_bdf,
        settings,
        mne_version=str(mne.__version__),
    )

    stored = process_runner._store_preprocessed_cache(
        raw=raw,
        file_path=fake_bdf,
        settings=settings,
        project_root=tmp_path / "project",
        mne_module=mne,
        audit_before=audit_before,
        n_rejected=2,
    )
    loaded, loaded_audit, n_rejected, status = process_runner._load_preprocessed_cache(
        file_path=fake_bdf,
        settings=settings,
        project_root=tmp_path / "project",
        mne_module=mne,
    )

    assert stored == "stored"
    assert payload["version"] == "preprocessed-raw-v2-filter-then-downsample"
    assert status == "hit"
    assert loaded is not None
    assert loaded.get_data().shape == raw.get_data().shape
    assert loaded_audit == audit_before
    assert n_rejected == 2


def test_preprocessed_cache_prunes_old_entries_for_same_source(tmp_path: Path) -> None:
    info = mne.create_info(["Cz", "Status"], sfreq=8.0, ch_types=["eeg", "stim"])
    raw = mne.io.RawArray(np.zeros((2, 16), dtype=float), info, verbose=False)
    fake_bdf = tmp_path / "fake.bdf"
    fake_bdf.write_bytes(b"raw source")
    project_root = tmp_path / "project"
    base_settings = {
        "stim_channel": "Status",
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "downsample_rate": 8,
        "enable_preprocessed_cache": True,
    }
    old_settings = dict(base_settings, high_pass=0.1)
    new_settings = dict(base_settings, high_pass=1.0)

    assert process_runner._store_preprocessed_cache(
        raw=raw,
        file_path=fake_bdf,
        settings=old_settings,
        project_root=project_root,
        mne_module=mne,
        audit_before={"file": "fake.bdf", "version": "old"},
        n_rejected=1,
    ) == "stored"
    old_payload = process_runner._preproc_cache_payload(
        fake_bdf,
        old_settings,
        mne_version=str(mne.__version__),
    )
    old_raw_path, old_meta_path = process_runner._preproc_cache_paths(
        project_root,
        fake_bdf,
        process_runner._preproc_cache_key(old_payload),
    )

    assert old_raw_path.exists()
    assert old_meta_path.exists()

    assert process_runner._store_preprocessed_cache(
        raw=raw,
        file_path=fake_bdf,
        settings=new_settings,
        project_root=project_root,
        mne_module=mne,
        audit_before={"file": "fake.bdf", "version": "new"},
        n_rejected=2,
    ) == "stored"
    new_payload = process_runner._preproc_cache_payload(
        fake_bdf,
        new_settings,
        mne_version=str(mne.__version__),
    )
    new_raw_path, new_meta_path = process_runner._preproc_cache_paths(
        project_root,
        fake_bdf,
        process_runner._preproc_cache_key(new_payload),
    )

    assert not old_raw_path.exists()
    assert not old_meta_path.exists()
    assert new_raw_path.exists()
    assert new_meta_path.exists()
    _, loaded_audit, n_rejected, status = process_runner._load_preprocessed_cache(
        file_path=fake_bdf,
        settings=new_settings,
        project_root=project_root,
        mne_module=mne,
    )
    assert status == "hit"
    assert loaded_audit == {"file": "fake.bdf", "version": "new"}
    assert n_rejected == 2
