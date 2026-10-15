"""Small synthetic execution/export checks for a frozen scientific bundle.

These fixtures exercise real processing, inference, serialization, and rendering
implementations. They do not certify empirical scientific accuracy or replace a
representative managed-project processing/compatibility acceptance pass.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path
from time import perf_counter

logger = logging.getLogger(__name__)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def preprocessing_probe(root: Path) -> dict[str, object]:
    import mne
    import numpy as np

    from Main_App.io.eeg_geometry import (
        BIOSEMI64_CHANNELS, attach_raw_biosemi64_geometry, cached_biosemi64_montage,
    )
    from Main_App.processing.preprocess import PREPROCESSING_ORDER_VERSION, perform_preprocessing

    sample_rate = 256
    rng = np.random.default_rng(73001)
    times = np.arange(sample_rate * 80) / sample_rate
    channels = [*BIOSEMI64_CHANNELS, "EXG1", "EXG2", "Status"]
    data = rng.normal(scale=1e-6, size=(len(channels), len(times)))
    data[:64] += 2e-6 * np.sin(2 * np.pi * 6 * times)
    data[-1] = 0
    data[-1, sample_rate * 5:sample_rate * 5 + 20] = 1
    data[-1, sample_rate * 20:sample_rate * 20 + 20] = 2
    raw = mne.io.RawArray(data, mne.create_info(channels, sample_rate, ["eeg"] * 66 + ["stim"]), verbose="ERROR")
    raw.set_montage(cached_biosemi64_montage(), on_missing="ignore", verbose="ERROR")
    attach_raw_biosemi64_geometry(raw, electrode_mapping_profile="anatomical_labels",
                                 retained_channels=BIOSEMI64_CHANNELS, reference_channels=("EXG1", "EXG2"),
                                 stim_channel="Status")
    settings = {
        "ref_channel1": "EXG1", "ref_channel2": "EXG2", "stim_channel": "Status",
        "high_pass": 0.1, "low_pass": 40.0, "downsample_rate": 128,
        "max_idx_keep": 64, "reject_thresh": 5.0, "kurtosis_screening_enabled": False,
        "line_noise_filter_enabled": False,
    }
    processed, rejected = perform_preprocessing(raw, settings, logger.info, "synthetic-acceptance")
    _check(processed is not None, f"Synthetic preprocessing failed: {settings.get('_fpvs_preprocessing_error')}")
    try:
        _check(processed.info["sfreq"] == 128, "Synthetic preprocessing did not downsample.")
        _check("EXG1" not in processed.ch_names and "EXG2" not in processed.ch_names,
               "Synthetic preprocessing retained the reference pair.")
        eeg = processed.get_data(picks="eeg")
        _check(eeg.shape[0] == 64 and np.isfinite(eeg).all(), "Synthetic processed EEG is invalid.")
        _check(np.max(np.abs(eeg.mean(axis=0))) < 1e-15, "Final average reference did not sum to zero.")
        events = mne.find_events(processed, stim_channel="Status", shortest_event=1, verbose="ERROR")
        _check(events[:, 2].tolist() == [1, 2], "Stim events changed during synthetic preprocessing.")
        target = root / "synthetic-preprocessed-raw.fif"
        processed.save(target, fmt="double", overwrite=False, verbose="ERROR")
        with mne.io.read_raw_fif(target, preload=True, verbose="ERROR") as reread:
            _check(np.array_equal(reread.get_data(), processed.get_data()), "FIF double-precision round trip changed samples.")
        return {"order_version": PREPROCESSING_ORDER_VERSION, "channel_count": len(processed.ch_names),
                "sampling_hz": 128, "event_codes": events[:, 2].tolist(), "rejected_channels": rejected,
                "kurtosis_screening": False, "fft_multinotch": False, "fif_roundtrip_exact": True}
    finally:
        if processed is not None:
            processed.close()


def free_harmonic_probe(root: Path) -> dict[str, object]:
    import numpy as np
    import pandas as pd

    from Tools.Free_Harmonic_Clustering.analysis import BIOSEMI64_CHANNELS, analyze_prepared_contrast
    from Tools.Free_Harmonic_Clustering.exports import export_free_harmonic_run
    from Tools.Free_Harmonic_Clustering.models import (
        AnalysisDesign, CohortWorkbook, FreeHarmonicMethodSpec, HarmonicSelectionMode,
        PreparationProvenance, PreparedContrast, ProjectContrastRequest,
    )
    from Tools.Free_Harmonic_Clustering.preparation import (
        build_frequency_window_plan, compute_participant_snr, l2_normalize_snr,
        select_harmonics, select_snr_harmonics,
    )

    started = perf_counter()
    root.mkdir()
    (root / "project.json").write_text(json.dumps({"name": "Synthetic prepared-tensor acceptance"}), encoding="utf-8")
    method = FreeHarmonicMethodSpec(max_harmonic_hz=2.4, harmonic_selection_mode=HarmonicSelectionMode.FIXED_HIGHEST,
                                    fixed_highest_harmonic_order=2, n_permutations=127, seed=73002)
    frequencies = np.arange(201) * 0.02
    columns = tuple(f"{frequency:.4f}_Hz" for frequency in frequencies)
    plan = build_frequency_window_plan(("Electrode", *columns), method)
    selected_positions = [columns.index(column) for column in plan.selected_frequency_columns]
    rng = np.random.default_rng(73003)
    amplitudes = [1 + rng.uniform(0.01, 0.1, (8, 64, len(columns))) for _ in range(2)]
    for values in amplitudes:
        values[:, :, 60] += 0.5
        values[:, :, 120] += 0.4
    amplitudes[0][:, 40:55, 60] += 0.4
    selected_a, selected_b = (values[:, :, selected_positions] for values in amplitudes)
    selection = select_harmonics(selected_a.mean(axis=(0, 1)), selected_b.mean(axis=(0, 1)), plan, method)
    snr_a, snr_b = (select_snr_harmonics(compute_participant_snr(values, plan), selection)
                    for values in (selected_a, selected_b))
    participants = tuple(f"P{index + 1:02}" for index in range(8))
    sources = []
    for arm, condition, values in zip(("a", "b"), ("Synthetic A", "Synthetic B"), amplitudes):
        for participant, array in zip(participants, values):
            path = root / "1 - Excel Data Files" / condition / f"{participant}_{condition}_Results.xlsx"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame = pd.DataFrame(array, columns=columns)
            frame.insert(0, "Electrode", BIOSEMI64_CHANNELS)
            frame.to_excel(path, sheet_name="FullFFT Amplitude (uV)", index=False)
            sources.append(CohortWorkbook(arm, condition, participant, condition, None, None, path,
                                          path.relative_to(root).as_posix(), 0.0, 0.0))
    prepared = PreparedContrast(
        request=ProjectContrastRequest(root, AnalysisDesign.PAIRED_CONDITIONS, "Synthetic A", "Synthetic B"),
        method=method, project_root=root, arm_a_label="Synthetic A", arm_b_label="Synthetic B",
        participant_ids_a=participants, participant_ids_b=participants, sensor_names=BIOSEMI64_CHANNELS,
        harmonic_orders=selection.selected_orders, harmonics_hz=selection.selected_harmonics_hz,
        snr_a=snr_a, snr_b=snr_b, values_a=l2_normalize_snr(snr_a), values_b=l2_normalize_snr(snr_b),
        selection=selection, frequency_plan=plan, source_workbooks=tuple(sources),
        provenance=PreparationProvenance(
            source_sheet="FullFFT Amplitude (uV)", grid_fingerprint=plan.grid_fingerprint,
            selected_columns_fingerprint=plan.selected_columns_fingerprint, frequency_resolution_hz=0.02,
            full_frequency_column_count=len(columns), selected_frequency_column_count=len(selected_positions),
            workbook_count=len(sources), header_read_seconds=0.0, amplitude_read_seconds=0.0,
            numeric_preparation_seconds=perf_counter() - started, total_seconds=perf_counter() - started,
            dataset_diagnostics=("Synthetic prepared-tensor fixture; managed-project provenance was not exercised.",),
        ),
    )
    result = analyze_prepared_contrast(prepared)
    _check(result.permutations_evaluated == 127 and np.isfinite(result.observed_t).all(),
           "Synthetic FHC inference did not finish its requested permutations.")
    receipt = export_free_harmonic_run(prepared, result, run_id="packaged-acceptance")
    for artifact in receipt.artifacts:
        _check(hashlib.sha256(artifact.path.read_bytes()).hexdigest() == artifact.sha256,
               f"FHC exported hash mismatch: {artifact.path.name}")
    _check(receipt.manifest_path.is_file(), "FHC run manifest was not published.")
    return {"participants": 8, "conditions": 2, "sensors": 64, "harmonics_hz": [1.2, 2.4],
            "permutations": 127, "artifact_count": len(receipt.artifacts),
            "manifest": str(receipt.manifest_path.relative_to(root.parent)),
            "scope": "synthetic prepared tensors, real inference and exports"}


def figure_probe(root: Path) -> dict[str, object]:
    import numpy as np
    import pandas as pd

    from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
    from Tools.Plot_Generator.worker import _Worker
    from Tools.Publication_Maps.models import PublicationMapRequest, PublicationMapResult, PublicationMetric
    from Tools.Publication_Maps.rendering import render_publication_figures

    input_root = root / "snr-input"
    condition = input_root / "Synthetic"
    condition.mkdir(parents=True)
    frequencies = np.arange(0, 4.01, 0.1)
    spectrum = 1 + np.exp(-((frequencies - 1.2) / 0.06) ** 2) * 3
    frame = pd.DataFrame(np.tile(spectrum, (64, 1)), columns=[f"{frequency:.4f}_Hz" for frequency in frequencies])
    frame.insert(0, "Electrode", BIOSEMI64_CHANNELS)
    frame.to_excel(condition / "P01_Synthetic_Results.xlsx", sheet_name="FullSNR", index=False)
    output = root / "2 - SNR Plots"
    worker = _Worker(folder=str(input_root), condition="Synthetic", roi_map={"All": list(BIOSEMI64_CHANNELS)},
                     selected_roi="All", title="Synthetic SNR acceptance", xlabel="Hz", ylabel="SNR",
                     x_min=0.0, x_max=4.0, y_min=0.0, y_max=5.0, out_dir=str(output))
    worker._run()
    _check(bool(list(output.rglob("*.png"))) and bool(list(output.rglob("*.pdf"))),
           "Synthetic SNR worker did not create matching figure formats.")
    grand = pd.DataFrame({"condition": ["Synthetic"] * 64, "metric": [PublicationMetric.BCA.value] * 64,
                          "map_label": ["Synthetic BCA"] * 64, "electrode": BIOSEMI64_CHANNELS,
                          "render_value": np.linspace(0.1, 1.0, 64), "is_montage_electrode": [True] * 64})
    result = PublicationMapResult(long_values=pd.DataFrame(), grand_average_values=grand)
    paths = render_publication_figures(result, PublicationMapRequest(
        input_root=input_root, output_root=root / "4 - Scalp Maps", conditions=("Synthetic",),
        project_root=root, metrics=(PublicationMetric.BCA,),
    ))
    _check({path.suffix for path in paths} == {".pdf", ".png"}, "Synthetic scalp export omitted a figure format.")
    return {"snr_png_pdf": True, "scalp_png_pdf": True, "scalp_channels": 64,
            "scope": "synthetic workbook SNR export and prepared-value scalp rendering"}


def run_workflows(output_root: Path) -> dict[str, object]:
    """Write only within one fresh, explicit diagnostic artifact directory."""
    output_root.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    result = {
        "synthetic_only": True,
        "preprocessing": preprocessing_probe(output_root),
        "free_harmonic_clustering": free_harmonic_probe(output_root / "fhc"),
        "figures": figure_probe(output_root),
    }
    widgets = sys.modules.get("PySide6.QtWidgets")
    result["qt_application_created"] = bool(widgets and widgets.QApplication.instance() is not None)
    _check(not result["qt_application_created"], "Scientific bundle probes must not create a Qt application.")
    result["elapsed_seconds"] = perf_counter() - started
    result["artifacts"] = [
        {"path": path.relative_to(output_root).as_posix(), "size_bytes": path.stat().st_size,
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(output_root.rglob("*")) if path.is_file()
    ]
    return result
