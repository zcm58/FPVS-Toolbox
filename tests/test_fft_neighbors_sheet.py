import pytest
from Main_App.Legacy_App.post_process_excel import (
    build_fft_neighbors_rows,
    write_results_workbook,
)

np = pytest.importorskip('numpy')
pd = pytest.importorskip('pandas')
load_workbook = pytest.importorskip('openpyxl').load_workbook


def test_fft_neighbors_sheet_written_with_expected_columns(tmp_path):
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

    write_results_workbook(
        str(workbook_path),
        {"FFT Amplitude (uV)": pd.DataFrame({"Electrode": ["Oz"], "1.2000_Hz": [1.0]})},
        neighbors_df,
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
