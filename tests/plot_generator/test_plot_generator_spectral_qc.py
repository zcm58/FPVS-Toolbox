import importlib.util

import pandas as pd
import pytest

from tests import repo_root
from Tools.Plot_Generator.spectral_qc_alerts import (
    build_spectral_qc_alert_message,
    whole_participant_exclusion_candidates,
)
from Tools.Plot_Generator.spectral_qc import (
    SpectralQcThresholds,
    flag_spectral_qc_electrode_outliers,
    interpolate_fullfft_electrode_data,
)
from Tools.Plot_Generator.source_identity import capture_stable_source_snapshot


def _import_module():
    path = repo_root() / "src" / "Tools" / "Plot_Generator" / "plot_generator.py"
    spec = importlib.util.spec_from_file_location("plot_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_workbook(path, *, bad_ft7=False, malformed_ft7=False):
    ft7_snr_1hz = "invalid" if malformed_ft7 else (50.0 if bad_ft7 else 1.0)
    ft7_snr_12hz = 50.0 if bad_ft7 else 2.0
    ft7_fft_1hz = 100.0 if bad_ft7 else 0.5
    ft7_fft_12hz = 100.0 if bad_ft7 else 0.5
    full_snr = pd.DataFrame(
        {
            "Electrode": ["Cz", "Pz", "FT7"],
            "1.0000_Hz": [1.0, 1.0, ft7_snr_1hz],
            "1.2000_Hz": [2.0, 2.0, ft7_snr_12hz],
        }
    )
    full_fft = pd.DataFrame(
        {
            "Electrode": ["Cz", "Pz", "FT7"],
            "1.0000_Hz": [0.5, 0.5, ft7_fft_1hz],
            "1.2000_Hz": [0.5, 0.5, ft7_fft_12hz],
        }
    )
    with pd.ExcelWriter(path) as writer:
        full_snr.to_excel(writer, sheet_name="FullSNR", index=False)
        full_fft.to_excel(writer, sheet_name="FullFFT Amplitude (uV)", index=False)


def test_spectral_qc_flags_off_harmonic_electrodes_without_changing_plot_values(
    tmp_path,
    monkeypatch,
):
    module = _import_module()
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    cond_dir = excel_root / "Cond"
    out_dir = project_root / "2 - SNR Plots"
    cond_dir.mkdir(parents=True)
    out_dir.mkdir()

    for index in range(1, 4):
        _write_workbook(
            cond_dir / f"P0{index}_Cond_Results.xlsx",
            bad_ft7=False,
        )
    _write_workbook(
        cond_dir / "P04_Cond_Results.xlsx",
        bad_ft7=True,
    )

    captured = {}
    messages = []

    def dummy_plot(self, freqs, roi_data, group_curves=None):
        captured["freqs"] = freqs
        captured["roi_data"] = roi_data
        png_path = self.out_dir / "qc-test.png"
        pdf_path = self.out_dir / "qc-test.pdf"
        png_path.write_bytes(b"png")
        pdf_path.write_bytes(b"pdf")
        self._record_figure_pair(
            png_path=png_path,
            pdf_path=pdf_path,
        )

    monkeypatch.setattr(module._Worker, "_plot", dummy_plot)
    monkeypatch.setattr(
        module._Worker,
        "_emit",
        lambda self, msg, *args: messages.append(msg) if msg else None,
    )
    monkeypatch.setattr(
        module._Worker,
        "_read_analysis_float",
        lambda self, option, fallback: 1.2 if option == "oddball_freq" else 0.0,
    )

    worker = module._Worker(
        folder=str(excel_root),
        condition="Cond",
        roi_map={"All": ["Cz", "Pz"]},
        selected_roi="All",
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=1.0,
        x_max=1.2,
        y_min=0.0,
        y_max=60.0,
        out_dir=str(out_dir),
        project_root=str(project_root),
        spectral_qc_enabled=True,
    )

    worker.run()

    assert captured["freqs"] == [1.0, 1.2]
    assert captured["roi_data"]["All"] == pytest.approx([1.0, 2.0])

    assert worker.spectral_qc_flags[0]["pid"] == "P04"
    assert not list(project_root.rglob("SNR_Unexpected_Peaks_*.xlsx"))
    assert (out_dir / "qc-test.png").is_file()
    assert (out_dir / "qc-test.pdf").is_file()
    assert not list(out_dir.glob("SNR_Plot_Run_*"))


def test_spectral_qc_reuses_full_snr_and_one_workbook_session(
    tmp_path,
    monkeypatch,
):
    module = _import_module()
    workbook = tmp_path / "P01_Cond_Results.xlsx"
    _write_workbook(workbook)
    worker = module._Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"Posterior": ["Cz", "Pz"]},
        selected_roi="Posterior",
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=1.0,
        x_max=1.2,
        y_min=0.0,
        y_max=5.0,
        out_dir=str(tmp_path / "plots"),
        spectral_qc_enabled=True,
    )
    original_snr_read = worker._read_full_snr_direct
    original_fft_read = worker._read_full_fft_direct
    reader_sessions = []
    snr_read_count = 0

    def traced_snr_read(*args, **kwargs):
        nonlocal snr_read_count
        snr_read_count += 1
        reader_sessions.append(kwargs["workbook_session"])
        return original_snr_read(*args, **kwargs)

    def traced_fft_read(*args, **kwargs):
        reader_sessions.append(kwargs["workbook_session"])
        return original_fft_read(*args, **kwargs)

    monkeypatch.setattr(worker, "_read_full_snr_direct", traced_snr_read)
    monkeypatch.setattr(worker, "_read_full_fft_direct", traced_fft_read)
    snapshot = capture_stable_source_snapshot(workbook)

    snr_input, fft_input, read_error = worker._read_workbook_sheets(
        workbook,
        snapshot=snapshot,
        included_electrodes_upper={"CZ", "PZ"},
    )
    snr_evidence, fft_evidence, reason = worker._assemble_spectral_qc_evidence(
        workbook,
        ordered_freqs=snr_input[1],
        excluded_electrodes=(),
        snr_input=snr_input,
        fft_input=fft_input,
        unavailable_reason=read_error,
    )

    assert snr_read_count == 1
    assert reader_sessions[0] is reader_sessions[1]
    assert reason is None
    assert set(snr_evidence) == {"CZ", "PZ", "FT7"}
    assert set(fft_evidence) == {"CZ", "PZ", "FT7"}


def test_malformed_unselected_qc_electrode_does_not_block_roi_plot_data(
    tmp_path,
    monkeypatch,
):
    module = _import_module()
    condition_dir = tmp_path / "Cond"
    condition_dir.mkdir()
    workbook = condition_dir / "P01_Cond_Results.xlsx"
    _write_workbook(workbook, malformed_ft7=True)
    worker = module._Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"Posterior": ["Cz", "Pz"]},
        selected_roi="Posterior",
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=1.0,
        x_max=1.2,
        y_min=0.0,
        y_max=5.0,
        out_dir=str(tmp_path / "plots"),
        spectral_qc_enabled=True,
    )
    monkeypatch.setattr(
        worker,
        "_read_analysis_float",
        lambda _option, fallback: fallback,
    )

    frequencies, subject_data = worker._collect_data(
        "Cond",
        excel_files=[workbook],
    )

    assert frequencies == [1.0, 1.2]
    assert subject_data["P01"]["Posterior"] == pytest.approx([1.0, 2.0])
    assert any(
        item["code"] == "spectral_qc_input_unavailable"
        for item in worker.warning_items
    )


def test_spectral_qc_inner_scan_honors_cooperative_cancellation():
    checkpoint_calls = 0

    def cancellation_checkpoint() -> bool:
        nonlocal checkpoint_calls
        checkpoint_calls += 1
        return checkpoint_calls >= 2

    result = flag_spectral_qc_electrode_outliers(
        condition="Cond",
        freqs=[1.0, 1.1, 1.2],
        subject_snr_data={
            pid: {"OZ": [1.0, 1.0, 1.0]}
            for pid in ("P01", "P02", "P03")
        },
        subject_fft_data={
            pid: {"OZ": [0.5, 0.5, 0.5]}
            for pid in ("P01", "P02", "P03")
        },
        source_workbooks={},
        oddball_freq=1.2,
        base_freq=6.0,
        thresholds=SpectralQcThresholds(),
        cancellation_checkpoint=cancellation_checkpoint,
    )

    assert checkpoint_calls == 2
    assert result.checked_cells == 0
    assert result.flagged_cells == 0


def test_spectral_qc_can_be_disabled(tmp_path, monkeypatch):
    module = _import_module()
    cond_dir = tmp_path / "Cond"
    cond_dir.mkdir()
    _write_workbook(
        cond_dir / "P01_Cond_Results.xlsx",
        bad_ft7=True,
    )

    captured = {}
    monkeypatch.setattr(
        module._Worker,
        "_plot",
        lambda self, freqs, roi_data, group_curves=None: captured.update(
            {"freqs": freqs, "roi_data": roi_data}
        ),
    )
    monkeypatch.setattr(module._Worker, "_emit", lambda *args, **kwargs: None)

    worker = module._Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"All": ["Cz", "Pz"]},
        selected_roi="All",
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=1.0,
        x_max=1.2,
        y_min=0.0,
        y_max=60.0,
        out_dir=str(tmp_path / "plots"),
        spectral_qc_enabled=False,
    )

    worker._run()

    assert captured["roi_data"]["All"] == [1.0, 2.0]


def test_optional_qc_conversion_failure_does_not_abort_plot_evidence(
    tmp_path,
    monkeypatch,
):
    module = _import_module()
    worker = module._Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"Posterior": ["Oz"]},
        selected_roi="Posterior",
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=1.0,
        x_max=1.0,
        y_min=0.0,
        y_max=5.0,
        out_dir=str(tmp_path / "plots"),
        spectral_qc_enabled=True,
    )
    snr_frame = pd.DataFrame(
        {"Electrode": ["Oz", "FT7"], "1.0_Hz": [2.0, "malformed"]}
    )
    fft_frame = pd.DataFrame(
        {"Electrode": ["Oz", "FT7"], "1.0_Hz": [1.0, 2.0]}
    )
    monkeypatch.setattr(
        worker,
        "_read_full_snr_direct",
        lambda *_args, **_kwargs: (snr_frame, [1.0], ["1.0_Hz"]),
    )
    monkeypatch.setattr(
        worker,
        "_read_full_fft_direct",
        lambda *_args, **_kwargs: (fft_frame, [1.0], ["1.0_Hz"]),
    )

    snr_evidence, fft_evidence, reason = worker._assemble_spectral_qc_evidence(
        tmp_path / "P01_Cond_Results.xlsx",
        ordered_freqs=[1.0],
        excluded_electrodes=(),
    )

    assert snr_evidence == {}
    assert fft_evidence == {}
    assert reason is not None and "read/conversion failed" in reason


def test_spectral_qc_with_zero_evaluated_cells_is_unavailable_not_complete(
    tmp_path,
    monkeypatch,
):
    module = _import_module()
    worker = module._Worker(
        folder=str(tmp_path),
        condition="Cond",
        roi_map={"Posterior": ["Oz"]},
        selected_roi="Posterior",
        title="t",
        xlabel="x",
        ylabel="y",
        x_min=1.0,
        x_max=1.0,
        y_min=0.0,
        y_max=5.0,
        out_dir=str(tmp_path / "plots"),
        spectral_qc_enabled=True,
    )
    messages: list[str] = []
    monkeypatch.setattr(worker, "_emit", lambda message, *_args: messages.append(message))
    worker._apply_spectral_qc_to_condition(
        "Cond",
        [1.0],
        {"P01": {"OZ": [2.0]}, "P02": {"OZ": [2.0]}},
        {"P01": {"OZ": [1.0]}, "P02": {"OZ": [1.0]}},
        {"P01": "P01.xlsx", "P02": "P02.xlsx"},
        {},
        ["P01", "P02"],
    )

    audit = worker.spectral_qc_runs[0]
    assert audit["status"] == "unavailable"
    assert audit["checked_cells"] == 0
    assert "at least 3 participants" in audit["status_reason"]
    assert worker.warning_items[0]["code"] == (
        "spectral_qc_insufficient_shared_evidence"
    )
    assert any("Spectral QC unavailable" in message for message in messages)


def test_fullfft_electrode_data_uses_interpolated_plot_grid():
    df = pd.DataFrame(
        {
            "Electrode": ["CPz", "Pz"],
            "4.0167_Hz": [5.0, 100.0],
            "4.0250_Hz": [1000.0, 2.0],
        }
    )

    fft_by_electrode = interpolate_fullfft_electrode_data(
        df,
        [4.0167, 4.0250],
        ["4.0167_Hz", "4.0250_Hz"],
        [4.02],
    )

    assert fft_by_electrode["CPZ"][0] > 300.0
    assert fft_by_electrode["PZ"][0] > 50.0


def test_spectral_qc_alert_message_recommends_reprocessing_flagged_electrodes():
    widespread_flags = [
        {
            "condition": "Erotic",
            "pid": "P12",
            "electrode": f"E{index:02d}",
            "flag_count": 10,
            "min_frequency_hz": 0.61,
            "max_frequency_hz": 16.11,
            "max_fft_amplitude_uv": 100.0 + index,
            "max_snr": 60.0 + index,
        }
        for index in range(64)
    ]
    flags = widespread_flags + [
            {
                "condition": "Neutral Angry",
                "pid": "P22",
                "electrode": "P2",
                "flag_count": 4,
                "min_frequency_hz": 16.0,
                "max_frequency_hz": 16.0,
                "max_fft_amplitude_uv": 113.99,
                "max_snr": 69.48,
            },
    ]
    message = build_spectral_qc_alert_message(
        flags,
    )
    candidates = whole_participant_exclusion_candidates(flags)

    assert "Unexpected SNR peaks were detected while generating SNR plots" in message
    assert "not the base frequency, not the oddball frequency" in message
    assert (
        "Example: a strong peak was detected at 16.00 Hz at electrode P2 "
        "in participant P22 during Neutral Angry"
    ) in message
    assert "Plots and processed data were not changed" in message
    assert "Whole-participant exclusion candidate(s)" in message
    assert "P12: all 64 scalp electrodes were flagged in Erotic" in message
    assert "Recommendation: exclude these participant(s), then reprocess" in message
    assert "Localized electrode candidates: 1 participant-electrode pair" in message
    assert "Full details were saved" not in message
    assert candidates == [
        {
            "pid": "P12",
            "conditions": ["Erotic"],
            "max_electrode_count": 64,
            "flag_count": 640,
        }
    ]
