from pathlib import Path

from Tools.Plot_Generator.excel_inputs import (
    _frequency_pairs_from_columns,
    _infer_subject_id_from_path,
    _select_frequency_pairs,
)


def test_infer_subject_id_is_case_insensitive() -> None:
    assert _infer_subject_id_from_path(Path("p10.bdf")) == "P10"
    assert _infer_subject_id_from_path(Path("P01.bdf")) == "P01"
    assert _infer_subject_id_from_path(Path("=p17.bdf")) == "P17"


def test_infer_subject_id_falls_back_to_cleaned_stem() -> None:
    assert _infer_subject_id_from_path(Path("control group.xlsx")) == "CONTROL GROUP"
    assert _infer_subject_id_from_path(Path("   .xlsx")) is None


def test_frequency_pairs_from_columns_keeps_numeric_hz_columns_sorted() -> None:
    columns = ["Electrode", "2.4_Hz", "not_frequency_Hz", "1.2_Hz", 3.6, "0.6_Hz"]

    assert _frequency_pairs_from_columns(columns) == [
        (0.6, "0.6_Hz"),
        (1.2, "1.2_Hz"),
        (2.4, "2.4_Hz"),
    ]


def test_select_frequency_pairs_applies_inclusive_range_with_tolerance() -> None:
    freq_pairs = [(0.9995, "0.9995_Hz"), (1.2, "1.2_Hz"), (2.0005, "2.0005_Hz"), (2.2, "2.2_Hz")]

    freqs, cols = _select_frequency_pairs(freq_pairs, x_min=1.0, x_max=2.0)

    assert freqs == [0.9995, 1.2, 2.0005]
    assert cols == ["0.9995_Hz", "1.2_Hz", "2.0005_Hz"]
