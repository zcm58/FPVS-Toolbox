import logging
import zipfile

import pytest
from Main_App.Shared import post_process_excel
from Main_App.Shared.post_process_excel import (
    _can_write_finite_metric_frame_direct,
    _column_widths,
    build_fft_neighbors_rows,
    write_results_workbook,
)

np = pytest.importorskip('numpy')
pd = pytest.importorskip('pandas')
load_workbook = pytest.importorskip('openpyxl').load_workbook


def _scalar_column_widths(frame):
    widths = []
    for column_index, header_name in enumerate(frame.columns):
        series = frame.iloc[:, column_index]
        max_len = max(
            len(str(header_name)),
            series.astype(str).map(len).max() if not series.empty else 0,
        )
        widths.append(int(max_len) + 4)
    return tuple(widths)


def test_column_width_blocks_preserve_scalar_string_length_semantics() -> None:
    frame = pd.DataFrame(
        {
            "Electrode": ["Oz", "PO8", None, "very-long-electrode-name"],
            "1.2000_Hz": [1.0, np.nan, -12345.6789, np.inf],
            "Mixed": ["short", 123, False, ""],
        }
    )

    assert _column_widths(frame) == _scalar_column_widths(frame)


def test_direct_metric_writer_guard_rejects_non_equivalent_frames() -> None:
    normal = pd.DataFrame(
        {
            "Electrode": ["Oz", "POz"],
            "1.2000_Hz": np.array([1.25, -0.5], dtype=np.float64),
        }
    )

    assert _can_write_finite_metric_frame_direct(normal)
    assert not _can_write_finite_metric_frame_direct(
        normal.astype({"1.2000_Hz": np.float32})
    )
    assert not _can_write_finite_metric_frame_direct(
        normal.assign(**{"1.2000_Hz": [1.25, np.nan]})
    )
    assert not _can_write_finite_metric_frame_direct(
        normal.assign(Electrode=["Oz", None])
    )


def test_direct_metric_writer_preserves_stable_xlsx_members(
    tmp_path,
    monkeypatch,
) -> None:
    columns = [f"{index / 100:.4f}_Hz" for index in range(257)]
    frame = pd.DataFrame(
        np.abs(np.random.default_rng(20260729).normal(size=(16, len(columns)))),
        columns=columns,
    )
    frame.insert(
        0,
        "Electrode",
        [f"E{index:02d}" for index in range(len(frame))],
    )
    frame.iat[0, 1] = -0.0
    frame.iat[1, 2] = 0.0
    neighbors = pd.DataFrame(
        {
            "file_name": ["demo.bdf"],
            "condition_label": ["Condition A"],
            "warning": [""],
        }
    )
    baseline_path = tmp_path / "pandas-baseline.xlsx"
    direct_path = tmp_path / "direct-metric.xlsx"

    monkeypatch.setattr(
        post_process_excel,
        "_can_write_finite_metric_frame_direct",
        lambda _frame: False,
    )
    write_results_workbook(
        str(baseline_path),
        {"FullFFT Amplitude (uV)": frame},
        neighbors,
    )

    monkeypatch.setattr(
        post_process_excel,
        "_can_write_finite_metric_frame_direct",
        _can_write_finite_metric_frame_direct,
    )
    write_results_workbook(
        str(direct_path),
        {"FullFFT Amplitude (uV)": frame},
        neighbors,
    )

    with zipfile.ZipFile(baseline_path) as baseline, zipfile.ZipFile(
        direct_path
    ) as direct:
        assert baseline.namelist() == direct.namelist()
        stable_members = [
            name
            for name in baseline.namelist()
            if name != "docProps/core.xml"
        ]
        assert {
            name: baseline.read(name)
            for name in stable_members
        } == {
            name: direct.read(name)
            for name in stable_members
        }


def test_cross_volume_staging_publishes_one_sequential_copy(
    tmp_path,
    monkeypatch,
) -> None:
    workbook_path = tmp_path / "staged-result.xlsx"
    copy_calls = []
    original_copyfile = post_process_excel.shutil.copyfile

    monkeypatch.setattr(
        post_process_excel,
        "_should_stage_workbook_locally",
        lambda _destination: True,
    )

    def record_copy(source, destination):
        copy_calls.append((source, destination))
        return original_copyfile(source, destination)

    monkeypatch.setattr(post_process_excel.shutil, "copyfile", record_copy)

    write_results_workbook(
        str(workbook_path),
        {
            "FFT Amplitude (uV)": pd.DataFrame(
                {"Electrode": ["Oz"], "1.2000_Hz": [1.25]}
            )
        },
    )

    assert workbook_path.is_file()
    assert len(copy_calls) == 1
    staged_source, publish_target = map(lambda value: value.resolve(), copy_calls[0])
    assert staged_source.parent != workbook_path.parent
    assert publish_target.parent == workbook_path.parent
    worksheet = load_workbook(workbook_path, data_only=True)["FFT Amplitude (uV)"]
    assert worksheet["A2"].value == "Oz"
    assert worksheet["B2"].value == 1.25


def test_cross_volume_staging_preserves_xlsx_members_except_core_timestamps(
    tmp_path,
    monkeypatch,
) -> None:
    direct_path = tmp_path / "direct.xlsx"
    staged_path = tmp_path / "staged.xlsx"
    frame = pd.DataFrame(
        {
            "Electrode": ["Oz", "POz"],
            "1.2000_Hz": [1.25, -0.5],
        }
    )

    monkeypatch.setattr(
        post_process_excel,
        "_should_stage_workbook_locally",
        lambda _destination: False,
    )
    write_results_workbook(str(direct_path), {"FFT Amplitude (uV)": frame})

    monkeypatch.setattr(
        post_process_excel,
        "_should_stage_workbook_locally",
        lambda _destination: True,
    )
    write_results_workbook(str(staged_path), {"FFT Amplitude (uV)": frame})

    with zipfile.ZipFile(direct_path) as direct, zipfile.ZipFile(staged_path) as staged:
        assert direct.namelist() == staged.namelist()
        stable_members = [
            name for name in direct.namelist() if name != "docProps/core.xml"
        ]
        assert {
            name: direct.read(name) for name in stable_members
        } == {
            name: staged.read(name) for name in stable_members
        }


def test_cross_volume_staging_preserves_existing_workbook_on_write_failure(
    tmp_path,
    monkeypatch,
) -> None:
    workbook_path = tmp_path / "existing-result.xlsx"
    original_bytes = b"existing workbook sentinel"
    workbook_path.write_bytes(original_bytes)

    monkeypatch.setattr(
        post_process_excel,
        "_should_stage_workbook_locally",
        lambda _destination: True,
    )

    def fail_to_excel(*_args, **_kwargs):
        raise RuntimeError("synthetic write failure")

    monkeypatch.setattr(pd.DataFrame, "to_excel", fail_to_excel)

    with pytest.raises(RuntimeError, match="synthetic write failure"):
        write_results_workbook(
            str(workbook_path),
            {"FFT Amplitude (uV)": pd.DataFrame({"Electrode": ["Oz"]})},
        )

    assert workbook_path.read_bytes() == original_bytes


def test_fft_neighbors_sheet_written_with_expected_columns(tmp_path, caplog):
    fs = 12.0
    n_samples = 120
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / fs)
    fft_amplitudes = np.arange(2 * len(freqs), dtype=float).reshape(2, len(freqs))

    rows = build_fft_neighbors_rows(
        file_name="demo.bdf",
        condition_label="Condition A",
        condition_id="Condition A",
        repetition_index="1",
        electrode_names=["Oz", "POz"],
        fft_amplitudes=fft_amplitudes,
        freqs=freqs,
        fs=fs,
        n_samples=n_samples,
        target_freq=1.2,
        crop_mode="55_onbin",
        n_step=10,
    )

    neighbor_columns = [
        "file_name",
        "condition_label",
        "condition_id",
        "repetition_index",
        "channel_or_roi",
        "target",
        "fs",
        "N",
        "T_sec",
        "df_hz",
        "k0",
        "f_bin_hz",
        *[f"amp_m{i}" for i in range(11, 0, -1)],
        *[f"amp_p{i}" for i in range(1, 12)],
        "warning",
    ]

    neighbors_df = pd.DataFrame(rows).reindex(columns=neighbor_columns)
    workbook_path = tmp_path / "result.xlsx"
    timing_records: list[dict[str, object]] = []

    caplog.set_level(logging.INFO, logger="Main_App.Shared.post_process_excel")
    write_results_workbook(
        str(workbook_path),
        {"FFT Amplitude (uV)": pd.DataFrame({"Electrode": ["Oz"], "1.2000_Hz": [1.0]})},
        neighbors_df,
        timing_sink=timing_records,
    )

    wb = load_workbook(workbook_path)
    assert "FFT and neighbors" in wb.sheetnames

    ws = wb["FFT and neighbors"]
    header = [cell.value for cell in ws[1]]

    expected_neighbor_cols = [
        *[f"amp_m{i}" for i in range(11, 0, -1)],
        *[f"amp_p{i}" for i in range(1, 12)],
    ]

    for col_name in expected_neighbor_cols:
        assert col_name in header
    assert len([c for c in header if c.startswith("amp_")]) == 22
    assert "amp_0" not in header
    assert "[EXCEL TIMING]" not in caplog.text
    assert "[EXCEL STAGE]" not in caplog.text
    assert {record["stage"] for record in timing_records} >= {
        "sheet_to_excel",
        "sheet_column_widths",
        "workbook_write_total",
    }


def test_fft_neighbors_rejects_nearest_bin_fallback() -> None:
    fs = 256.0
    n_samples = 32256
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / fs)
    fft_amplitudes = np.zeros((1, len(freqs)), dtype=float)

    with pytest.raises(ValueError, match="Nearest-bin fallback is disabled"):
        build_fft_neighbors_rows(
            file_name="demo.bdf",
            condition_label="Condition A",
            condition_id="Condition A",
            repetition_index="1",
            electrode_names=["Oz"],
            fft_amplitudes=fft_amplitudes,
            freqs=freqs,
            fs=fs,
            n_samples=n_samples,
            target_freq=1.2,
            crop_mode="55_onbin",
            n_step=640,
        )
